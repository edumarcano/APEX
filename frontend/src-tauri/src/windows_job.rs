use std::{
    ffi::{c_void, OsStr, OsString},
    os::windows::{
        ffi::{OsStrExt, OsStringExt},
        io::{FromRawHandle, RawHandle},
    },
    path::{Path, PathBuf},
};
use tokio::fs::File;
use windows_sys::Win32::{
    Foundation::{
        CloseHandle, SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT, WAIT_OBJECT_0, WAIT_TIMEOUT,
    },
    Security::SECURITY_ATTRIBUTES,
    System::{
        JobObjects::{
            CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
            TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        },
        Pipes::CreatePipe,
        Threading::{
            CreateProcessW, DeleteProcThreadAttributeList, InitializeProcThreadAttributeList,
            UpdateProcThreadAttribute, WaitForSingleObject, CREATE_NO_WINDOW,
            EXTENDED_STARTUPINFO_PRESENT, PROCESS_INFORMATION, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            PROC_THREAD_ATTRIBUTE_JOB_LIST, STARTF_USESTDHANDLES, STARTUPINFOEXW,
        },
    },
};

pub enum ChildInput {
    Pipe(File),
}

pub struct JobGuard(pub isize);
unsafe impl Send for JobGuard {}
impl Drop for JobGuard {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0 as HANDLE);
        }
    }
}

pub struct OwnedChild {
    process: isize,
    pid: u32,
    job: JobGuard,
}
unsafe impl Send for OwnedChild {}

impl OwnedChild {
    pub fn id(&self) -> u32 {
        self.pid
    }
    pub fn try_wait(&mut self) -> Result<Option<()>, ()> {
        unsafe {
            match WaitForSingleObject(self.process as HANDLE, 0) {
                WAIT_OBJECT_0 => Ok(Some(())),
                WAIT_TIMEOUT => Ok(None),
                _ => Err(()),
            }
        }
    }
    pub async fn wait(&mut self) -> Result<(), ()> {
        loop {
            if self.try_wait()?.is_some() {
                return Ok(());
            }
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
    }
    pub async fn kill(&mut self) -> Result<(), ()> {
        unsafe {
            if TerminateJobObject(self.job.0 as HANDLE, 1) == 0 {
                return Err(());
            }
        }
        self.wait().await
    }
}

const WINDOWS_MAX_PATH: usize = 260;

fn normalize_short_verbatim_path(path: &Path, suffix_reserve: usize) -> PathBuf {
    let original: Vec<u16> = path.as_os_str().encode_wide().collect();
    let prefix: Vec<u16> = r"\\?\".encode_utf16().collect();
    if !original.starts_with(&prefix) {
        return path.to_path_buf();
    }
    let ordinary = &original[prefix.len()..];
    let drive_absolute =
        ordinary.len() >= 3 && ordinary[1] == b':' as u16 && ordinary[2] == b'\\' as u16;
    if drive_absolute && ordinary.len().saturating_add(suffix_reserve) < WINDOWS_MAX_PATH - 1 {
        PathBuf::from(OsString::from_wide(ordinary))
    } else {
        path.to_path_buf()
    }
}

fn normalize_command_executable(command: &str, suffix_reserve: usize) -> String {
    let Some(quoted) = command.strip_prefix('"') else {
        return command.to_owned();
    };
    let Some(end) = quoted.find('"') else {
        return command.to_owned();
    };
    let executable = normalize_short_verbatim_path(Path::new(&quoted[..end]), suffix_reserve);
    format!("\"{}\"{}", executable.display(), &quoted[end + 1..])
}

impl Drop for OwnedChild {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.process as HANDLE);
        }
    }
}

#[cfg(test)]
#[allow(clippy::items_after_test_module)]
mod tests {
    use super::*;
    use std::{io::Write, process::Command};
    use tokio::io::{AsyncBufReadExt, AsyncReadExt};
    use windows_sys::Win32::System::Threading::{
        OpenProcess, TerminateProcess, PROCESS_SYNCHRONIZE, PROCESS_TERMINATE,
    };

    static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    #[test]
    #[allow(clippy::zombie_processes)]
    fn sentinel_worker() {
        let _lock = ENV_LOCK.lock().unwrap();
        if std::env::var_os("APEX_JOB_SENTINEL_CHILD").is_none() {
            return;
        }
        let executable = std::env::current_exe().unwrap();
        let grandchild = Command::new(executable)
            .args([
                "--exact",
                "windows_job::tests::sentinel_grandchild",
                "--nocapture",
            ])
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .unwrap();
        println!("READY {}", grandchild.id());
        std::io::stdout().flush().unwrap();
        std::thread::park();
    }

    #[test]
    fn sentinel_grandchild() {
        let _lock = ENV_LOCK.lock().unwrap();
        if std::env::var_os("APEX_JOB_SENTINEL_CHILD").is_some() {
            println!("EXTERNAL_READY {}", std::process::id());
            std::io::stdout().flush().unwrap();
            std::thread::park();
        }
    }

    #[test]
    fn verbatim_resource_worker() {
        let _lock = ENV_LOCK.lock().unwrap();
        if std::env::var_os("APEX_VERBATIM_RESOURCE_CHILD").is_none() {
            return;
        }
        let argv0 = std::env::args_os().next().unwrap();
        let current_exe = std::env::current_exe().unwrap();
        let argv0_wide: Vec<u16> = argv0.encode_wide().collect();
        let prefix: Vec<u16> = r"\\?\".encode_utf16().collect();
        let verbatim = argv0_wide.starts_with(&prefix);
        println!("RESOURCE_ARGV0_VERBATIM={verbatim} argv0={argv0:?} current_exe={current_exe:?}");
        // The frozen runtime resolves resources relative to the executable spelling
        // supplied to CreateProcess. current_exe is retained for diagnostics because
        // Windows may canonicalize it independently of argv0.
        let executable = PathBuf::from(argv0);
        let mut resource_path = executable.parent().unwrap().as_os_str().to_os_string();
        resource_path.push(r"\_internal\language_tags\data\json/index.json");
        let resource = PathBuf::from(resource_path);
        assert_eq!(std::fs::read(resource).unwrap(), b"resource-ok");
        println!("VERBATIM_RESOURCE_READY");
    }

    #[tokio::test]
    async fn production_spawn_normalizes_verbatim_app_argv_and_resource_paths() {
        let test_executable = std::env::current_exe().unwrap();
        let bundle = std::env::temp_dir().join(format!("apex-path-{}", uuid::Uuid::new_v4()));
        let suffix = r"\_internal\language_tags\data\json/index.json";
        assert!(
            bundle.as_os_str().encode_wide().count() + suffix.encode_utf16().count()
                < WINDOWS_MAX_PATH - 1,
            "test resource path must fit ordinary Win32 path semantics"
        );
        let resource = bundle.join("_internal/language_tags/data/json");
        std::fs::create_dir_all(&resource).unwrap();
        std::fs::write(resource.join("index.json"), b"resource-ok").unwrap();
        let executable = bundle.join("apex-backend.exe");
        std::fs::copy(&test_executable, &executable).unwrap();
        let verbatim_exe = PathBuf::from(format!(r"\\?\{}", executable.display()));
        let verbatim_bundle = PathBuf::from(format!(r"\\?\{}", bundle.display()));
        let command = format!(
            "\"{}\" --exact windows_job::tests::verbatim_resource_worker --nocapture",
            verbatim_exe.display()
        );
        let spawned = {
            let _lock = ENV_LOCK.lock().unwrap();
            let old_flag = std::env::var_os("APEX_VERBATIM_RESOURCE_CHILD");
            std::env::set_var("APEX_VERBATIM_RESOURCE_CHILD", "1");
            let spawned = spawn_command(
                &verbatim_exe,
                &verbatim_bundle,
                &command,
                suffix.encode_utf16().count(),
            );
            if let Some(value) = old_flag {
                std::env::set_var("APEX_VERBATIM_RESOURCE_CHILD", value);
            } else {
                std::env::remove_var("APEX_VERBATIM_RESOURCE_CHILD");
            }
            spawned
        };
        let (mut child, _stdin, mut stdout, mut stderr) =
            spawned.expect("production spawn should normalize short verbatim paths");
        tokio::time::timeout(std::time::Duration::from_secs(15), child.wait())
            .await
            .expect("verbatim-path child should exit within the test bound")
            .expect("exact process handle should report child exit");
        let mut stdout_bytes = Vec::new();
        let mut stderr_bytes = Vec::new();
        stdout.read_to_end(&mut stdout_bytes).await.unwrap();
        stderr.read_to_end(&mut stderr_bytes).await.unwrap();
        assert!(
            String::from_utf8_lossy(&stdout_bytes).contains("VERBATIM_RESOURCE_READY"),
            "child should read the mixed-separator resource path; stderr: {}",
            String::from_utf8_lossy(&stderr_bytes)
        );
        assert!(String::from_utf8_lossy(&stdout_bytes).contains("RESOURCE_ARGV0_VERBATIM=false"));
        drop(child);
        std::fs::remove_dir_all(bundle).unwrap();
    }

    #[test]
    fn long_verbatim_paths_keep_extended_prefix() {
        let long = PathBuf::from(format!(r"\\?\C:\{}", "a".repeat(WINDOWS_MAX_PATH)));
        assert_eq!(normalize_short_verbatim_path(&long, 0), long);
    }

    #[test]
    fn job_terminates_a_descendant_assigned_at_process_creation() {
        let _lock = ENV_LOCK.lock().unwrap();
        let executable = std::env::current_exe().unwrap();
        let bundle = executable.parent().unwrap();
        let mut external = Command::new(&executable)
            .args([
                "--exact",
                "windows_job::tests::sentinel_grandchild",
                "--nocapture",
            ])
            .env("APEX_JOB_SENTINEL_CHILD", "1")
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
            .unwrap();
        let mut external_reader = std::io::BufReader::new(external.stdout.take().unwrap());
        let mut external_line = String::new();
        loop {
            external_line.clear();
            assert_ne!(
                std::io::BufRead::read_line(&mut external_reader, &mut external_line).unwrap(),
                0,
                "external sentinel should acknowledge startup"
            );
            if external_line.starts_with("EXTERNAL_READY ") {
                break;
            }
        }
        let external_pid: u32 = external_line
            .trim()
            .strip_prefix("EXTERNAL_READY ")
            .unwrap()
            .parse()
            .unwrap();
        let external_handle =
            unsafe { OpenProcess(PROCESS_SYNCHRONIZE | PROCESS_TERMINATE, 0, external_pid) };
        assert!(!external_handle.is_null());
        std::env::set_var("APEX_JOB_SENTINEL_CHILD", "1");
        let command = format!(
            "\"{}\" --exact windows_job::tests::sentinel_worker --nocapture",
            executable.display()
        );
        let spawned = spawn_command(&executable, bundle, &command, 0);
        std::env::remove_var("APEX_JOB_SENTINEL_CHILD");
        let (child, _stdin, stdout, _stderr) = spawned.unwrap();
        let mut reader = tokio::io::BufReader::new(stdout);
        let runtime = tokio::runtime::Runtime::new().unwrap();
        let ready = loop {
            let mut line = String::new();
            let count = runtime
                .block_on(reader.read_line(&mut line))
                .expect("sentinel worker should acknowledge its descendant");
            assert_ne!(count, 0, "sentinel worker exited before its acknowledgment");
            if line.starts_with("READY ") {
                break line;
            }
        };
        let descendant_pid: u32 = ready
            .strip_prefix("READY ")
            .and_then(|line| line.trim().parse().ok())
            .expect("sentinel acknowledgment should include its child PID");
        let descendant = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, descendant_pid) };
        let root_process = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, 0, child.id()) };
        assert!(!descendant.is_null(), "descendant should still be running");
        assert!(
            !root_process.is_null(),
            "managed child should still be running"
        );
        assert_eq!(unsafe { WaitForSingleObject(descendant, 0) }, WAIT_TIMEOUT);
        assert_eq!(
            unsafe { WaitForSingleObject(root_process, 0) },
            WAIT_TIMEOUT
        );
        assert_eq!(
            unsafe { WaitForSingleObject(external_handle, 0) },
            WAIT_TIMEOUT
        );

        drop(child);
        assert_eq!(
            unsafe { WaitForSingleObject(root_process, 10_000) },
            WAIT_OBJECT_0,
            "closing the owned Job Object should terminate its root process"
        );
        assert_eq!(
            unsafe { WaitForSingleObject(descendant, 10_000) },
            WAIT_OBJECT_0,
            "job cleanup should reap the descendant without a name or port lookup"
        );
        assert_eq!(
            unsafe { WaitForSingleObject(external_handle, 0) },
            WAIT_TIMEOUT,
            "closing the owned job must not affect an unrelated external process"
        );
        unsafe {
            TerminateProcess(external_handle, 0);
            WaitForSingleObject(external_handle, 10_000);
            CloseHandle(external_handle);
            CloseHandle(root_process);
            CloseHandle(descendant);
        }
        external.wait().expect("external sentinel should be reaped");
    }
}

fn wide(value: &OsStr) -> Vec<u16> {
    value.encode_wide().chain(Some(0)).collect()
}

unsafe fn pipe_pair(
    sa: &mut SECURITY_ATTRIBUTES,
    parent_write: bool,
) -> Result<(HANDLE, HANDLE), ()> {
    let mut read = std::ptr::null_mut();
    let mut write = std::ptr::null_mut();
    if CreatePipe(&mut read, &mut write, sa, 0) == 0 {
        return Err(());
    }
    let parent = if parent_write { write } else { read };
    if SetHandleInformation(parent, HANDLE_FLAG_INHERIT, 0) == 0 {
        CloseHandle(read);
        CloseHandle(write);
        return Err(());
    }
    Ok((read, write))
}

unsafe fn set_attribute(
    list: *mut c_void,
    attribute: usize,
    value: *const c_void,
    size: usize,
) -> Result<(), ()> {
    if UpdateProcThreadAttribute(
        list,
        0,
        attribute,
        value,
        size,
        std::ptr::null_mut(),
        std::ptr::null(),
    ) == 0
    {
        Err(())
    } else {
        Ok(())
    }
}

pub fn spawn(
    exe: &Path,
    bundle: &Path,
    launch_id: &str,
    resource_path_reserve: usize,
) -> Result<(OwnedChild, ChildInput, File, File), ()> {
    let command = format!(
        "\"{}\" serve --managed --launch-id {}",
        exe.display(),
        launch_id
    );
    spawn_command(exe, bundle, &command, resource_path_reserve)
}

fn spawn_command(
    exe: &Path,
    bundle: &Path,
    command: &str,
    resource_path_reserve: usize,
) -> Result<(OwnedChild, ChildInput, File, File), ()> {
    let executable_path = normalize_short_verbatim_path(exe, resource_path_reserve);
    let bundle_path = normalize_short_verbatim_path(bundle, resource_path_reserve);
    let command = normalize_command_executable(command, resource_path_reserve);
    unsafe {
        let mut sa = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: std::ptr::null_mut(),
            bInheritHandle: 1,
        };
        let (child_stdin, parent_stdin) = pipe_pair(&mut sa, true)?;
        let (parent_stdout, child_stdout) = match pipe_pair(&mut sa, false) {
            Ok(pair) => pair,
            Err(_) => {
                CloseHandle(child_stdin);
                CloseHandle(parent_stdin);
                return Err(());
            }
        };
        let (parent_stderr, child_stderr) = match pipe_pair(&mut sa, false) {
            Ok(pair) => pair,
            Err(_) => {
                for h in [child_stdin, parent_stdin, parent_stdout, child_stdout] {
                    CloseHandle(h);
                }
                return Err(());
            }
        };

        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            for h in [
                child_stdin,
                parent_stdin,
                parent_stdout,
                child_stdout,
                parent_stderr,
                child_stderr,
            ] {
                CloseHandle(h);
            }
            return Err(());
        }
        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &limits as *const _ as *const c_void,
            std::mem::size_of_val(&limits) as u32,
        ) == 0
        {
            CloseHandle(job);
            for h in [
                child_stdin,
                parent_stdin,
                parent_stdout,
                child_stdout,
                parent_stderr,
                child_stderr,
            ] {
                CloseHandle(h);
            }
            return Err(());
        }

        let mut needed = 0usize;
        InitializeProcThreadAttributeList(std::ptr::null_mut(), 2, 0, &mut needed);
        if needed == 0 {
            CloseHandle(job);
            for h in [
                child_stdin,
                parent_stdin,
                parent_stdout,
                child_stdout,
                parent_stderr,
                child_stderr,
            ] {
                CloseHandle(h);
            }
            return Err(());
        }
        let mut storage = vec![0usize; needed.div_ceil(std::mem::size_of::<usize>())];
        let attrs = storage.as_mut_ptr().cast::<c_void>();
        if InitializeProcThreadAttributeList(attrs, 2, 0, &mut needed) == 0 {
            CloseHandle(job);
            for h in [
                child_stdin,
                parent_stdin,
                parent_stdout,
                child_stdout,
                parent_stderr,
                child_stderr,
            ] {
                CloseHandle(h);
            }
            return Err(());
        }
        struct AttributeList(*mut c_void);
        impl Drop for AttributeList {
            fn drop(&mut self) {
                unsafe {
                    DeleteProcThreadAttributeList(self.0);
                }
            }
        }
        let _attrs_guard = AttributeList(attrs);
        let handles = [child_stdin, child_stdout, child_stderr];
        let jobs = [job];
        if set_attribute(
            attrs,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
            handles.as_ptr().cast(),
            std::mem::size_of_val(&handles),
        )
        .is_err()
            || set_attribute(
                attrs,
                PROC_THREAD_ATTRIBUTE_JOB_LIST as usize,
                jobs.as_ptr().cast(),
                std::mem::size_of_val(&jobs),
            )
            .is_err()
        {
            CloseHandle(job);
            for h in [
                child_stdin,
                parent_stdin,
                parent_stdout,
                child_stdout,
                parent_stderr,
                child_stderr,
            ] {
                CloseHandle(h);
            }
            return Err(());
        }

        let mut startup: STARTUPINFOEXW = std::mem::zeroed();
        startup.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = child_stdin;
        startup.StartupInfo.hStdOutput = child_stdout;
        startup.StartupInfo.hStdError = child_stderr;
        startup.lpAttributeList = attrs.cast();
        let application = wide(executable_path.as_os_str());
        let directory = wide(bundle_path.as_os_str());
        let mut command_wide: Vec<u16> =
            OsStr::new(&command).encode_wide().chain(Some(0)).collect();
        let mut info: PROCESS_INFORMATION = std::mem::zeroed();
        let created = CreateProcessW(
            application.as_ptr(),
            command_wide.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
            EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW,
            std::ptr::null(),
            directory.as_ptr(),
            &startup.StartupInfo,
            &mut info,
        );
        for h in [child_stdin, child_stdout, child_stderr] {
            CloseHandle(h);
        }
        if created == 0 {
            CloseHandle(job);
            for h in [parent_stdin, parent_stdout, parent_stderr] {
                CloseHandle(h);
            }
            return Err(());
        }
        CloseHandle(info.hThread);
        let child = OwnedChild {
            process: info.hProcess as isize,
            pid: info.dwProcessId,
            job: JobGuard(job as isize),
        };
        let stdin_file = std::fs::File::from_raw_handle(parent_stdin as RawHandle);
        let stdout_file = std::fs::File::from_raw_handle(parent_stdout as RawHandle);
        let stderr_file = std::fs::File::from_raw_handle(parent_stderr as RawHandle);
        Ok((
            child,
            ChildInput::Pipe(File::from_std(stdin_file)),
            File::from_std(stdout_file),
            File::from_std(stderr_file),
        ))
    }
}
