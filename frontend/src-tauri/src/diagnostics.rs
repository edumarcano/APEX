use std::{
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};
use tauri::Manager;
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWriteExt};

const SESSION_CAP: u64 = 1024 * 1024;
const TRUNCATION_MARKER: &[u8] = b"truncated\n";

pub struct LogFile {
    path: PathBuf,
    kind: &'static str,
    generation: u64,
}

impl LogFile {
    pub fn serve(directory: impl Into<PathBuf>, generation: u64) -> Self {
        Self::named(directory, "backend.log", "serve", generation)
    }

    pub fn setup(directory: impl Into<PathBuf>, generation: u64) -> Self {
        Self::named(directory, "setup.log", "setup", generation)
    }

    fn named(
        directory: impl Into<PathBuf>,
        name: &str,
        kind: &'static str,
        generation: u64,
    ) -> Self {
        Self {
            path: directory.into().join(name),
            kind,
            generation,
        }
    }
}

pub fn spawn_stderr_drain<R>(reader: R, log: Option<LogFile>)
where
    R: AsyncRead + Unpin + Send + 'static,
{
    tauri::async_runtime::spawn(async move {
        let _ = drain_stderr(reader, log).await;
    });
}

pub async fn drain_stderr<R>(mut reader: R, log: Option<LogFile>) -> u64
where
    R: AsyncRead + Unpin,
{
    let mut output = match log {
        Some(log) => open_session(&log).await.ok(),
        None => None,
    };
    let mut consumed = 0u64;
    let mut buffer = [0u8; 8192];
    loop {
        let count = match reader.read(&mut buffer).await {
            Ok(0) | Err(_) => break,
            Ok(count) => count,
        };
        consumed += count as u64;
        if let Some(file) = output.as_mut() {
            if write_limited(file, &buffer[..count]).await.is_err() {
                output = None;
            }
        }
    }
    consumed
}

async fn open_session(log: &LogFile) -> std::io::Result<LimitedFile> {
    if let Some(parent) = log.path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    rotate_if_needed(&log.path).await?;
    let mut file = tokio::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log.path)
        .await?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0);
    let header = format!(
        "ts={stamp} kind={} generation={}\n",
        log.kind, log.generation
    );
    file.write_all(header.as_bytes()).await?;
    Ok(LimitedFile {
        file,
        written: header.len() as u64,
        truncated: false,
    })
}

async fn rotate_if_needed(path: &Path) -> std::io::Result<()> {
    let length = match tokio::fs::metadata(path).await {
        Ok(metadata) => metadata.len(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };
    if length < SESSION_CAP {
        return Ok(());
    }
    let backup = backup_path(path);
    if tokio::fs::try_exists(&backup).await? {
        tokio::fs::remove_file(&backup).await?;
    }
    tokio::fs::rename(path, backup).await
}

fn backup_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(".1");
    PathBuf::from(name)
}

struct LimitedFile {
    file: tokio::fs::File,
    written: u64,
    truncated: bool,
}

async fn write_limited(file: &mut LimitedFile, chunk: &[u8]) -> std::io::Result<()> {
    if file.truncated {
        return Ok(());
    }
    let room = SESSION_CAP.saturating_sub(file.written);
    if room == 0 {
        file.file.write_all(TRUNCATION_MARKER).await?;
        file.truncated = true;
        return Ok(());
    }
    let take = std::cmp::min(room as usize, chunk.len());
    file.file.write_all(&chunk[..take]).await?;
    file.written += take as u64;
    if take < chunk.len() {
        file.file.write_all(TRUNCATION_MARKER).await?;
        file.truncated = true;
    }
    Ok(())
}

pub fn note(app: &tauri::AppHandle, file_name: &str, line: &str) {
    if file_name.contains(['/', '\\']) || file_name == ".." {
        return;
    }
    let Ok(directory) = app.path().app_log_dir() else {
        return;
    };
    if std::fs::create_dir_all(&directory).is_err() {
        return;
    }
    let Ok(mut output) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(directory.join(file_name))
    else {
        return;
    };
    let _ = writeln!(output, "{line}");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn temp_dir(name: &str) -> PathBuf {
        let directory = std::env::temp_dir().join(format!(
            "apex-diag-{name}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|elapsed| elapsed.as_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(&directory).unwrap();
        directory
    }

    #[tokio::test]
    async fn session_cap_keeps_a_marker_and_consumes_the_reader() {
        let directory = temp_dir("cap");
        let payload = vec![b'a'; SESSION_CAP as usize + 64 * 1024];
        let consumed = drain_stderr(
            Cursor::new(payload.clone()),
            Some(LogFile::serve(&directory, 4)),
        )
        .await;
        let bytes = std::fs::read(directory.join("backend.log")).unwrap();
        assert_eq!(consumed, payload.len() as u64);
        assert!(bytes.len() <= SESSION_CAP as usize + TRUNCATION_MARKER.len());
        assert!(bytes.ends_with(TRUNCATION_MARKER));
        let _ = std::fs::remove_dir_all(directory);
    }

    #[tokio::test]
    async fn oversized_log_rotates_to_a_single_backup() {
        let directory = temp_dir("rotate");
        let current = directory.join("backend.log");
        let backup = directory.join("backend.log.1");
        std::fs::write(&backup, b"previous").unwrap();
        std::fs::write(&current, vec![b'x'; SESSION_CAP as usize]).unwrap();

        let consumed = drain_stderr(
            Cursor::new(Vec::<u8>::new()),
            Some(LogFile::serve(&directory, 9)),
        )
        .await;

        assert_eq!(consumed, 0);
        assert_eq!(
            std::fs::read(&backup).unwrap(),
            vec![b'x'; SESSION_CAP as usize]
        );
        let header = std::fs::read_to_string(&current).unwrap();
        assert!(header.contains("kind=serve"));
        assert!(header.contains("generation=9"));
        assert!(!header.contains("previous"));
        let _ = std::fs::remove_dir_all(directory);
    }
}
