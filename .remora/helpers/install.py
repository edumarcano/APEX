"""Preview, install, or check the declared Remora payload from a trusted checkout."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = {
    "standards/engineering.md": ".remora/standards/engineering.md",
    "standards/documentation.md": ".remora/standards/documentation.md",
    "standards/testing.md": ".remora/standards/testing.md",
    "skills/remora-audit-documentation/SKILL.md":
        ".agents/skills/remora-audit-documentation/SKILL.md",
    **{f"skills/{name}/SKILL.md": f".agents/skills/{name}/SKILL.md"
       for name in ("remora-plan-change", "remora-implement-plan",
                    "remora-fix-regression", "remora-review-change",
                    "remora-prepare-pr", "remora-prepare-release",
                    "remora-remediate-project",
                    "remora-audit-tests", "remora-audit-harness")},
    "helpers/install.py": ".remora/helpers/install.py",
}
PROFILES = ("python", "typescript", "local", "web")
PROFILE_FILES = {f"profiles/{name}.md": f".remora/profiles/{name}.md" for name in PROFILES}
INPUTS = (*PAYLOAD, *PROFILE_FILES, "skills/remora-bootstrap/SKILL.md", "templates/AGENTS.md")
MANIFEST = ".remora/installation.json"
ENVIRONMENTS = ("codex", "cursor", "antigravity")
FIELDS = {"schema_version", "remora_version", "source_revision", "selected_profiles",
          "target_environments", "managed_files"}
BUNDLE = "payload.zip"
BUNDLE_INDEX = "bundle.json"
EXPOSED = {"SKILL.md": "skills/remora-bootstrap/SKILL.md",
           "helpers/install.py": "helpers/install.py",
           "templates/AGENTS.md": "templates/AGENTS.md",
           **{name: name for name in PAYLOAD if name.startswith("standards/")}}


class Conflict(Exception):
    """An unsafe operation or an integrity failure; no replacement is permitted."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_bundle(committed: dict[str, bytes]):
    """Check our two-scalar metadata and literal required-resource subset only.

    This is not a YAML/Markdown parser. Backtick-delimited target-root standard
    and skill file paths in installed skills declare required bundle resources.
    Conditional reading does not make a resource optional to ship.
    """
    destinations = set(PAYLOAD.values())
    for name, data in committed.items():
        if not name.startswith("skills/") or not name.endswith("/SKILL.md"):
            continue
        text = data.decode("utf-8").replace("\r\n", "\n")
        lines = text.splitlines()
        if not lines or lines[0] != "---" or "---" not in lines[1:]:
            raise Conflict(f"Missing skill frontmatter: {name}")
        end = lines.index("---", 1)
        fields = {}
        for line in lines[1:end]:
            field = re.fullmatch(r"(name|description): ([^\n]+)", line)
            if not field or field[1] in fields or not field[2].strip():
                raise Conflict(f"Unsupported skill metadata: {name}")
            fields[field[1]] = field[2]
        description = fields.get("description", "")
        if (not re.match(r"[A-Za-z]", description)
                or re.search(r":(?:\s|$)|\s#", description)
                or description.strip().lower() in {"true", "false", "null", "yes", "no", "on", "off"}):
            raise Conflict(f"Unsupported plain-scalar description: {name}")
        if (set(fields) != {"name", "description"}
                or fields["name"] != Path(name).parent.name
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields["name"])
                or len(fields["name"]) > 64):
            raise Conflict(f"Invalid skill identity or description: {name}")
        if name not in PAYLOAD:
            continue  # Bootstrap uses source-relative links, checked by maintainer tooling.
        references = re.findall(
            r"`((?:\.remora/standards/|\.agents/skills/)[^`\n]+)`", text)
        for reference in references:
            if reference not in destinations:
                raise Conflict(f"Missing declared bundle resource: {name}: {reference}")


def inspect_path(path: Path):
    """Reject links/reparse points, including dangling links and ancestors."""
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise Conflict(f"Unsafe link or reparse point: {part}")
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise Conflict(f"Ancestor is not a directory: {part}")


def source_inputs(root: Path) -> tuple[str, dict[str, bytes]]:
    """Read only fixed, committed regular files; never run target tooling."""
    inspect_path(root.absolute())
    if (root / BUNDLE_INDEX).exists():
        if (root / ".git").exists():
            raise Conflict("Ambiguous distribution: checkout contains package metadata")
        return package_inputs(root)
    def git(*arguments):
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(root),
                                 *arguments], capture_output=True, check=False)
        if result.returncode:
            raise OSError(f"Cannot read pinned source: git {' '.join(arguments)}: "
                          f"{result.stderr.decode('utf-8', errors='replace').strip()}")
        return result.stdout

    top = Path(os.fsdecode(git("rev-parse", "--show-toplevel").strip())).resolve()
    if top != root.resolve():
        raise Conflict("Installer must belong to the source checkout root")
    revision = git("rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
    ls_out = git("ls-tree", "-z", revision, "--", *INPUTS)
    entries = {}
    for part in ls_out.split(b"\0"):
        if not part:
            continue
        meta, path_b = part.split(b"\t", 1)
        entries[path_b.decode("utf-8")] = meta
    for name in INPUTS:
        inspect_path(root / name)
        meta = entries.get(name)
        if not meta or not meta.startswith((b"100644 blob ", b"100755 blob ")):
            raise Conflict(f"Source input is not a committed regular file: {name}")
    proc = subprocess.Popen(["git", "--no-optional-locks", "-C", str(root),
                             "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    in_bytes = b"".join(f"{revision}:{name}\n".encode("utf-8") for name in INPUTS)
    out, err = proc.communicate(in_bytes)
    if proc.returncode:
        raise OSError(f"Cannot read pinned source: git cat-file --batch: {err.decode('utf-8', errors='replace').strip()}")
    committed = {}
    idx = 0
    for name in INPUTS:
        hdr_end = out.find(b"\n", idx)
        if hdr_end == -1:
            raise Conflict(f"Source input cannot be read from git: {name}")
        hdr = out[idx:hdr_end].split()
        if len(hdr) < 3 or hdr[1] != b"blob":
            raise Conflict(f"Source input is not a committed regular file: {name}")
        try:
            size = int(hdr[2])
        except ValueError:
            raise Conflict(f"Source input cannot be read from git: {name}")
        start = hdr_end + 1
        data = out[start:start + size]
        if len(data) != size:
            raise Conflict(f"Source input truncated: {name}")
        committed[name] = data
        idx = start + size + 1
        if (root / name).read_bytes().replace(b"\r\n", b"\n") != committed[name].replace(b"\r\n", b"\n"):
            raise Conflict(f"Source input has local modifications: {name}")
    if git("diff", "--no-ext-diff", "--no-textconv", "--name-only", revision,
           "--", *INPUTS) or git("diff", "--cached", "--no-ext-diff", "--no-textconv",
                                 "--name-only", revision, "--", *INPUTS):
        raise Conflict("Installation inputs have local modifications; use a pinned clean source")
    validate_bundle(committed)
    return revision, committed


def source_payload(root: Path, profiles=()) -> tuple[str, dict[str, bytes]]:
    revision, committed = source_inputs(root)
    mapping = {**PAYLOAD, **{name: target for name, target in PROFILE_FILES.items()
                           if Path(name).stem in profiles}}
    return revision, {target: committed[name] for name, target in mapping.items()}


def package_inputs(root: Path):
    """Read a reviewed local package; hashes are consistency checks, not signatures."""
    for name in (BUNDLE_INDEX, BUNDLE):
        inspect_path(root / name)
    index = json.loads((root / BUNDLE_INDEX).read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if (not isinstance(index, dict) or set(index) != {"source_revision", "files"}
            or not isinstance(index["source_revision"], str)
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", index["source_revision"])
            or not isinstance(index["files"], dict) or set(index["files"]) != set(INPUTS)):
        raise Conflict("Unsupported bundle inventory")
    with zipfile.ZipFile(root / BUNDLE) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(INPUTS):
            raise Conflict("Unsafe or incomplete archive inventory")
        committed = {}
        for item in archive.infolist():
            if item.file_size > 2_000_000 or item.compress_size > 2_000_000:
                raise Conflict("Oversized bundle asset")
            mode = item.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or item.is_dir():
                raise Conflict("Archive asset is not a regular file")
            data = archive.read(item)
            if digest(data) != index["files"][item.filename]:
                raise Conflict(f"Bundle digest mismatch: {item.filename}")
            committed[item.filename] = data
    # Visible bootstrap resources and the executing helper must match the archive.
    for outer, inner in EXPOSED.items():
        inspect_path(root / outer)
        if (root / outer).read_bytes() != committed[inner]:
            raise Conflict(f"Packaged resource differs: {outer}")
    validate_bundle(committed)
    return index["source_revision"], committed


def expected_manifest(revision: str, payload: dict[str, bytes], environments: list[str], profiles=()):
    return {"schema_version": 1, "remora_version": "development",
            "source_revision": revision, "selected_profiles": sorted(set(profiles)),
            "target_environments": sorted(set(environments)),
            "managed_files": {name: digest(data) for name, data in payload.items()}}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Conflict(f"Duplicate manifest field: {key}")
        result[key] = value
    return result


def read_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Conflict(f"Malformed manifest: {error}") from error
    if not isinstance(manifest, dict) or set(manifest) != FIELDS:
        raise Conflict("Unsupported manifest fields")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise Conflict("Unsupported manifest schema_version")
    profiles = manifest["selected_profiles"]
    if (manifest["remora_version"] != "development" or not isinstance(profiles, list)
            or any(not isinstance(item, str) or item not in PROFILES for item in profiles)
            or profiles != sorted(set(profiles))):
        raise Conflict("Unsupported release label or selected_profiles")
    revision = manifest["source_revision"]
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise Conflict("Invalid source_revision")
    environments = manifest["target_environments"]
    if (not isinstance(environments, list) or not environments
            or any(not isinstance(item, str) or item not in ENVIRONMENTS for item in environments)
            or environments != sorted(set(environments))):
        raise Conflict("Invalid target_environments")
    files = manifest["managed_files"]
    # Recognize only authored inventories, never arbitrary manifest paths.
    current = set(PAYLOAD.values()) | {PROFILE_FILES[f"profiles/{name}.md"] for name in profiles}
    previous_release = set(PAYLOAD.values()) - {".agents/skills/remora-remediate-project/SKILL.md"}
    previous_pr = previous_release - {".agents/skills/remora-prepare-release/SKILL.md"}
    previous_v01 = previous_pr - {".agents/skills/remora-prepare-pr/SKILL.md"}
    legacy = [set(PAYLOAD.values()) - {".remora/helpers/install.py"},
              previous_release,
              previous_release - {".remora/helpers/install.py"},
              previous_pr,
              previous_pr - {".remora/helpers/install.py"},
              previous_v01,
              previous_v01 - {".remora/helpers/install.py"},
              {".remora/standards/engineering.md", ".remora/standards/documentation.md",
               ".agents/skills/remora-audit-documentation/SKILL.md"},
              {".remora/standards/engineering.md"}]
    if (not isinstance(files, dict) or (set(files) != current
            and (profiles or set(files) not in legacy))):
        raise Conflict("Unsupported managed_files inventory or unsafe path")
    if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
           for value in files.values()):
        raise Conflict("Invalid managed file digest")
    return manifest


def inspect_target(target: Path, payload: dict[str, bytes]):
    inspect_path(target)
    if not target.is_dir():
        raise ValueError("Target must be an existing directory")
    for name in (*payload, MANIFEST):
        inspect_path(target / name)
        if (target / name).exists() and not (target / name).is_file():
            raise Conflict(f"Destination is not a regular file: {name}")


def validate(target: Path, expected: dict):
    manifest = read_manifest(target / MANIFEST)
    if manifest != expected:
        raise Conflict("Manifest differs from pinned source or requested selections; use explicit update")
    for name, wanted in expected["managed_files"].items():
        path = target / name
        if not path.is_file():
            raise Conflict(f"Missing managed file: {name}")
        if digest(path.read_bytes()) != wanted:
            raise Conflict(f"Modified managed file: {name}")


def create_file(target: Path, name: str, data: bytes, created: list[str]):
    path = target / name
    inspect_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    inspect_path(path)
    try:
        with path.open("xb") as stream:
            created.append(name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise Conflict(f"Destination appeared before creation: {name}") from error
    inspect_path(path)
    if path.read_bytes() != data:
        raise Conflict(f"Written file failed byte verification: {name}")


def install(target: Path, payload: dict[str, bytes], expected: dict, created: list[str]):
    # Repeat the whole preflight after preview and before any writes.
    inspect_target(target, payload)
    for name in (*payload, MANIFEST):
        if (target / name).exists():
            raise Conflict(f"Unmanaged destination is occupied: {name}")
    for name, data in payload.items():
        create_file(target, name, data, created)
    inspect_target(target, payload)
    for name, data in payload.items():
        if (target / name).read_bytes() != data:
            raise Conflict(f"Payload changed before manifest publication: {name}")
    data = (json.dumps(expected, indent=2, sort_keys=True) + "\n").encode("utf-8")
    create_file(target, MANIFEST, data, created)


def previous_expected(root: Path, manifest: dict):
    """Verify a known old inventory without executing its installer."""
    if (root / BUNDLE_INDEX).exists():
        revision, payload = source_payload(root, manifest["selected_profiles"])
    else:
        inspect_path(root.absolute())
        def git(*args):
            result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                                    capture_output=True, check=False)
            if result.returncode:
                raise OSError("Cannot inspect previous trusted source")
            return result.stdout
        if Path(os.fsdecode(git("rev-parse", "--show-toplevel").strip())).resolve() != root.resolve():
            raise Conflict("Previous source must be a checkout root")
        revision = git("rev-parse", "HEAD^{commit}").decode("ascii").strip()
        reverse = {target: source for source, target in {**PAYLOAD, **PROFILE_FILES}.items()}
        sources = {reverse[name] for name in manifest["managed_files"]} | {"helpers/install.py"}
        committed = {}
        for name in sources:
            inspect_path(root / name)
            if not git("ls-tree", revision, "--", name).startswith((b"100644 blob ", b"100755 blob ")):
                raise Conflict(f"Previous source asset is not regular: {name}")
            data = git("show", f"{revision}:{name}")
            if (root / name).read_bytes().replace(b"\r\n", b"\n") != data.replace(b"\r\n", b"\n"):
                raise Conflict(f"Previous source asset modified: {name}")
            committed[name] = data
        if git("diff", "--no-ext-diff", "--no-textconv", "--name-only", revision, "--", *sorted(sources)):
            raise Conflict("Previous source has staged or working changes")
        payload = {name: committed[reverse[name]] for name in manifest["managed_files"]}
    expected = expected_manifest(revision, payload, manifest["target_environments"], manifest["selected_profiles"])
    if manifest != expected:
        raise Conflict("Previous installation does not match trusted source")
    return expected


def lifecycle_plan(target: Path, old: dict, payload: dict, expected: dict | None):
    names = sorted(set(old["managed_files"]) | set(payload))
    inspect_target(target, {name: b"" for name in names})
    validate(target, old)
    before = {}
    for name in [*names, MANIFEST]:
        path = target / name
        before[name] = path.read_bytes() if path.exists() else None
        if name not in old["managed_files"] and name != MANIFEST and before[name] is not None:
            raise Conflict(f"Unmanaged destination is occupied: {name}")
    after = {name: payload.get(name) for name in names}
    after[MANIFEST] = ((json.dumps(expected, indent=2, sort_keys=True) + "\n").encode("utf-8")
                       if expected is not None else None)
    identity = target.stat()
    plan = {"target": str(target), "identity": [identity.st_dev, identity.st_ino],
            "before": {name: digest(data) if data is not None else None for name, data in before.items()},
            "after": {name: digest(data) if data is not None else None for name, data in after.items()}}
    token = digest(json.dumps(plan, sort_keys=True).encode("utf-8"))
    return token, plan, before, after


def apply_lifecycle(target: Path, backup: Path, plan: dict, before: dict, after: dict, created: list[str]):
    """Keep before-images outside the target; no automatic rollback or bulk cleanup."""
    if before == after:
        print("Lifecycle operation verified; no changes")
        return
    inspect_path(backup.absolute())
    backup = Path(os.path.abspath(backup))
    if backup == target or backup.is_relative_to(target) or target.is_relative_to(backup):
        raise Conflict("Backup must be outside and separate from the target")
    if backup.exists():
        raise Conflict("Backup destination must not exist")
    backup.mkdir(parents=True)
    for name, data in before.items():
        if data is not None:
            create_file(backup, name, data, [])
    create_file(backup, "operation.json", (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode(), [])
    print(f"Recovery before-images: {backup}")

    def unchanged(name):
        inspect_path(target / name)
        current = (target / name).read_bytes() if (target / name).exists() else None
        if current != before[name]:
            raise Conflict(f"Destination changed since preview: {name}")
    identity = target.stat()
    if [identity.st_dev, identity.st_ino] != plan["identity"]:
        raise Conflict("Target root changed")
    for name in before:
        unchanged(name)
    # Invalidate completion before mutation. A failure never leaves a valid old manifest.
    unchanged(MANIFEST)
    (target / MANIFEST).unlink()
    for name in sorted(set(before) - {MANIFEST}):
        if before[name] == after[name]:
            continue
        unchanged(name)
        path = target / name
        if before[name] is not None:
            path.unlink()
        if after[name] is not None:
            create_file(target, name, after[name], created)
    inspect_target(target, {name: b"" for name in after})
    for name, data in after.items():
        if name == MANIFEST:
            continue
        actual = (target / name).read_bytes() if (target / name).exists() else None
        if actual != data:
            raise Conflict(f"Payload changed before completion: {name}")
    if after[MANIFEST] is not None:
        create_file(target, MANIFEST, after[MANIFEST], created)
    print("Lifecycle operation complete; project-owned guidance preserved. Inspect obsolete routing separately.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--environment", choices=ENVIRONMENTS, action="append")
    parser.add_argument("--profile", choices=PROFILES, action="append")
    parser.add_argument("--clear-profiles", action="store_true", help="explicitly select no profiles for update")
    parser.add_argument("--source", type=Path, help="separately trusted checkout or bootstrap package")
    parser.add_argument("--previous-source", type=Path, help="trusted source matching the old installation")
    parser.add_argument("--expect-plan", help="digest printed by an update/removal preview")
    parser.add_argument("--backup", type=Path, help="new private directory outside target for before-images")
    modes = parser.add_mutually_exclusive_group()
    parser.add_argument("--apply", action="store_true", help="apply the selected operation")
    modes.add_argument("--check", action="store_true", help="check against this pinned source")
    modes.add_argument("--update", action="store_true", help="preview explicit replacement")
    modes.add_argument("--remove", action="store_true", help="preview managed removal")
    arguments = parser.parse_args(argv)
    if arguments.clear_profiles and (not arguments.update or arguments.profile):
        parser.error("--clear-profiles requires --update and cannot combine with --profile")
    if arguments.check and (arguments.environment or arguments.profile or arguments.apply):
        parser.error("--check reads selections from the manifest and cannot apply")
    if arguments.remove and (arguments.environment or arguments.profile):
        parser.error("--remove reads selections from the old manifest")
    if not (arguments.check or arguments.remove or arguments.update) and not arguments.environment:
        parser.error("preview/apply requires at least one --environment")
    created = []
    try:
        # Inspect lexical ancestors before collapsing '..', which could hide a link.
        inspect_path(arguments.target.absolute())
        target = Path(os.path.abspath(arguments.target))
        source = arguments.source or SOURCE_ROOT
        local = arguments.check and arguments.source is None and (SOURCE_ROOT / "installation.json").is_file()
        if not arguments.check and arguments.source is None and (SOURCE_ROOT / "installation.json").is_file():
            raise Conflict("Installed helper writes require a separately trusted --source")
        if arguments.check or arguments.update or arguments.remove:
            inspect_target(target, {})
            old = read_manifest(target / MANIFEST) if (target / MANIFEST).exists() else None
            if old is None:
                raise Conflict("Missing installation manifest")
        else:
            old = None
        profiles = arguments.profile if arguments.profile is not None else (old["selected_profiles"] if old else [])
        if arguments.clear_profiles:
            profiles = []
        if local:
            inspect_target(target, {name: b"" for name in old["managed_files"]})
            validate(target, old)
            print("Local manifest/hash consistency verified; trusted-source provenance NOT checked")
            return 0
        if arguments.update or arguments.remove:
            if arguments.previous_source is None:
                raise Conflict("Lifecycle operations require --previous-source")
            old = previous_expected(arguments.previous_source, old)
        revision, payload = source_payload(source, profiles)
        inspect_target(target, payload)
        manifest_path = target / MANIFEST
        if arguments.check:
            if not manifest_path.is_file():
                raise Conflict("Missing installation manifest")
            environments = old["target_environments"]
        else:
            environments = arguments.environment or old["target_environments"]
        expected = expected_manifest(revision, payload, environments, profiles)
        if arguments.update or arguments.remove:
            if arguments.remove:
                payload, expected = {}, None
            token, plan, before, after = lifecycle_plan(target, old, payload, expected)
            print(f"Plan SHA-256: {token}")
            for name in sorted(before):
                if before[name] != after[name]:
                    action = "remove" if after[name] is None else ("add" if before[name] is None else "replace")
                    print(f"Would {action}: {name}")
            if arguments.apply:
                if arguments.expect_plan != token or arguments.backup is None:
                    raise Conflict("Apply requires matching --expect-plan and new --backup directory")
                apply_lifecycle(target, arguments.backup, plan, before, after, created)
            return 0
        if manifest_path.exists():
            validate(target, expected)
            print("Installation verified against pinned source; no changes")
            return 0
        for name in payload:
            if (target / name).exists():
                raise Conflict(f"Unmanaged destination is occupied: {name}")
        if not arguments.apply:
            print(f"Preview pinned source {revision}; no changes")
            for name in (*payload, MANIFEST):
                print(f"Would create: {name}")
            return 0
        install(target, payload, expected, created)
        print(f"Installed and verified pinned source {revision}")
        return 0
    except Conflict as error:
        print(f"Installation conflict: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile, KeyError, TypeError) as error:
        print(f"Installation incomplete: {error}", file=sys.stderr)
        return 2
    finally:
        if created:
            print("Created files: " + ", ".join(created))


if __name__ == "__main__":
    sys.exit(main())
