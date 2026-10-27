from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER_TEMPLATE = ROOT / "frontend/src-tauri/nsis/installer.nsi"
RESOURCE_FILES = (
    r"backend-bundle\apex-backend.exe",
    r"backend-bundle\apex.exe",
    r"backend-bundle\_internal\apex-2.0.0.dist-info\entry_points.txt",
    r"backend-bundle\_internal\apex-2.0.0.dist-info\METADATA",
    r"backend-bundle\_internal\apex-2.0.0.dist-info\WHEEL",
)
RESOURCE_DIRS = (
    "backend-bundle",
    r"backend-bundle\_internal",
    r"backend-bundle\_internal\apex-2.0.0.dist-info",
    "current-only-resource",
)
RESOURCE_ANCESTORS = ("backend-bundle",)


def _function(source: str, name: str) -> str:
    start = source.index(f"Function {name}\n")
    end = source.index("FunctionEnd", start) + len("FunctionEnd")
    return source[start:end]


def _render_loop_blocks(source: str) -> str:
    def replace(match: object) -> str:
        name, body = match.group(1), match.group(2)
        values: tuple[object, ...]
        if name == "resources":
            values = tuple((path,) for path in RESOURCE_FILES)
        elif name == "resources_dirs":
            values = RESOURCE_DIRS
        elif name == "resources_ancestors":
            values = RESOURCE_ANCESTORS
        elif name == "binaries":
            values = ()
        else:
            raise AssertionError(f"Unexpected NSIS template loop: {name}")
        rendered: list[str] = []
        for value in values:
            line = body
            if name == "resources":
                line = line.replace("{{this.[1]}}", str(value[0]))
                line = line.replace("{{this}}", str(value[0]))
            else:
                line = line.replace("{{this}}", str(value))
            rendered.append(line)
        return "".join(rendered)

    import re

    rendered = re.sub(
        r"\{\{#each (resources|resources_dirs|resources_ancestors|binaries)\}\}(.*?)\{\{/each\}\}",
        replace,
        source,
        flags=re.DOTALL,
    )
    # Tauri's Handlebars rendering normalizes escaped path separators in the
    # upstream NSIS template before passing it to makensis.
    return rendered.replace("\\\\", "\\")


def _render_uninstall_section(template: str) -> str:
    section = template.split("Section Uninstall\n", 1)[1].split("SectionEnd", 1)[0]
    # The production Section's association and deep-link entries depend on
    # generated shell-integration macros. Keep its file, registration, and
    # startup cleanup behavior under test without introducing those unrelated
    # platform integrations into this focused synthetic installer.
    start = section.index("  ; Delete app associations")
    end = section.index("  ; Delete uninstaller", start)
    section = section[:start] + section[end:]
    start = section.index("  ; Remove shortcuts if not updating")
    end = section.index("  ; Remove registry information for add/remove programs", start)
    section = section[:start] + section[end:]
    section = _render_loop_blocks(section)
    return "Section Uninstall\n" + section + "SectionEnd\n"


def _compiler() -> Path | None:
    configured = os.environ.get("APEX_NSIS_COMPILER")
    if configured:
        candidate = Path(configured)
        if not candidate.is_file():
            raise AssertionError(f"APEX_NSIS_COMPILER does not exist: {candidate}")
        return candidate
    discovered = shutil.which("makensis")
    if discovered:
        return Path(discovered)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        for candidate in (
            Path(local_app_data) / "tauri/NSIS/makensis.exe",
            Path(local_app_data) / "tauri/NSIS/Bin/makensis.exe",
        ):
            if candidate.is_file():
                return candidate
    return None


def _plugin_dir(compiler: Path) -> Path:
    for candidate in (
        compiler.parent / "Plugins/x86-unicode",
        compiler.parent.parent / "Plugins/x86-unicode",
    ):
        if (candidate / "System.dll").is_file() and (candidate / "nsExec.dll").is_file():
            return candidate
    raise AssertionError(f"System/nsExec NSIS plugins were not found beside {compiler}")


class NsisUpgradeHarnessTests(unittest.TestCase):
    """Execute compiled production NSIS cleanup and uninstaller sections safely."""

    @classmethod
    def setUpClass(cls) -> None:
        compiler = _compiler()
        if compiler is None:
            raise unittest.SkipTest("NSIS compiler unavailable; CI supplies APEX_NSIS_COMPILER")
        if os.name != "nt":
            raise unittest.SkipTest("The production NSIS lifecycle harness requires Windows")
        cls.compiler = compiler
        cls.plugin_dir = _plugin_dir(compiler)
        cls.temp = tempfile.TemporaryDirectory(prefix="apex-nsis-upgrade-")
        cls.base = Path(cls.temp.name)
        cls.identity = uuid.uuid4().hex[:12]
        cls.product_name = f"APEX_NSIS_TEST_{cls.identity}"
        cls.manufacturer = f"APEX_NSIS_VENDOR_{cls.identity}"
        cls.foreign_run_name = f"APEX_NSIS_TEST_FOREIGN_{cls.identity}"
        cls.run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        cls.test_key = rf"Software\APEX_NSIS_TEST_{cls.identity}"
        cls.manufacturer_key = rf"Software\{cls.manufacturer}"
        cls.install_root = rf"Software\{cls.manufacturer}\{cls.product_name}"
        cls.uninstall_key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{cls.product_name}"
        cls.addClassCleanup(cls.temp.cleanup)
        cls.addClassCleanup(cls._delete_test_registry)
        cls.source = INSTALLER_TEMPLATE.read_text(encoding="utf-8")
        cls.old_installer = cls.base / "seed-old-install.exe"
        cls.helper_installer = cls.base / "production-upgrade-helper.exe"
        cls._compile(cls.old_installer, cls._old_installer_script())
        cls._compile(cls.helper_installer, cls._helper_script())
        cls.process_exe = cls.base / "APEX.exe"
        cls._compile(cls.process_exe, cls._process_script())

    @classmethod
    def _compile(cls, output: Path, script: str) -> None:
        nsi = output.with_suffix(".nsi")
        nsi.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [str(cls.compiler), "/V2", str(nsi)],
            cwd=cls.base,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0 or not output.is_file():
            raise AssertionError(
                f"makensis failed for {nsi.name} (exit {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}\n--- generated tail ---\n{nsi.read_text(encoding='utf-8')[-700:]}"
            )

    @classmethod
    def _preamble(cls, output: Path, *, hooks: bool = False) -> str:
        target = str(output).replace("\\", "\\\\")
        hook = ""
        if hooks:
            hook = f'''\
!macro NSIS_HOOK_PREUNINSTALL
  WriteRegStr HKCU "{cls.test_key}" "invoked" "yes"
  ReadRegStr $R9 HKCU "{cls.test_key}" "failure"
  StrCmp $R9 "nonzero" 0 +2
  SetErrorLevel 37
  StrCmp $R9 "nonzero" 0 +2
  Abort "Synthetic prior uninstaller failure"
!macroend
!macro NSIS_HOOK_POSTUNINSTALL
  ReadRegStr $R9 HKCU "{cls.test_key}" "leave_shell"
  StrCmp $R9 "yes" nsis_test_leave_shell 0
  Goto nsis_test_finish_uninstall
nsis_test_leave_shell:
  FileOpen $9 "$INSTDIR\\apex-desktop.exe" w
  FileWrite $9 "intentionally retained"
  FileClose $9
nsis_test_finish_uninstall:
  WriteRegStr HKCU "{cls.test_key}" "postuninstall" "completed"
  SetErrorLevel 0
!macroend
'''
        return f'''\
Unicode true
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "StrFunc.nsh"
!insertmacro GetParent
!insertmacro GetFileName
${{StrCase}}
${{StrLoc}}
${{UnStrCase}}
${{UnStrLoc}}
!define PRODUCTNAME "{cls.product_name}"
!define MANUFACTURER "{cls.manufacturer}"
!define MANUKEY "Software\\${{MANUFACTURER}}"
!define MAINBINARYNAME "apex-desktop"
!define INSTALLMODE "currentUser"
!define SHCTX HKCU
!define MANUPRODUCTKEY "${{MANUKEY}}\\${{PRODUCTNAME}}"
!define UNINSTKEY "{cls.uninstall_key}"
!define TESTKEY "{cls.test_key}"
!define OUTFILE "{target}"
{hook}SilentInstall silent
OutFile "${{OUTFILE}}"
RequestExecutionLevel user
InstallDir "$TEMP\\APEX_NSIS_TEST_{cls.identity}"
Var UpdateMode
Var PassiveMode
'''

    @classmethod
    def _old_installer_script(cls) -> str:
        uninstall = _render_uninstall_section(cls.source)
        check_process = _function(cls.source, "un.CheckAPEXProcesses")
        detect_process = _function(cls.source, "un.DetectAPEXProcess")
        check_reparse = _function(cls.source, "un.CheckNoReparsePoint")
        seed_files = ["apex-desktop.exe", *RESOURCE_FILES]
        create_files = "\n".join(
            f'''  FileOpen $9 "$INSTDIR\\{path.replace('/', chr(92))}" w
  FileWrite $9 "seed"
  FileClose $9'''
            for path in seed_files
        )
        return (
            cls._preamble(cls.old_installer, hooks=True)
            + f'''\
Section "Seed registered previous version"
  CreateDirectory "$INSTDIR"
  CreateDirectory "$INSTDIR\\backend-bundle"
  CreateDirectory "$INSTDIR\\backend-bundle\\_internal\\apex-2.0.0.dist-info"
{create_files}
  WriteRegStr HKCU "${{MANUPRODUCTKEY}}" "" "$INSTDIR"
  WriteRegStr HKCU "${{UNINSTKEY}}" "UninstallString" '$\\"$INSTDIR\\uninstall.exe$\\"'
  WriteRegStr HKCU "${{UNINSTKEY}}" "DisplayVersion" "2.0.0"
  WriteRegStr HKCU "${{UNINSTKEY}}" "MainBinaryName" "apex-desktop.exe"
  WriteRegStr HKCU "${{TESTKEY}}" "failure" ""
  WriteRegStr HKCU "${{TESTKEY}}" "leave_shell" ""
  WriteRegStr HKCU "${{TESTKEY}}" "invoked" ""
  WriteRegStr HKCU "{cls.run_key}" "${{PRODUCTNAME}}" '$\\"$INSTDIR\\apex-desktop.exe$\\" --autostart'
  WriteRegStr HKCU "{cls.run_key}" "{cls.foreign_run_name}" "foreign command"
  WriteUninstaller "$INSTDIR\\uninstall.exe"
SectionEnd
'''
            + "\n"
            + uninstall
            + "\n"
            + '''\
Function un.onInit
  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}
FunctionEnd
'''
            + "\n"
            + check_process
            + "\n"
            + detect_process
            + "\n"
            + check_reparse
        )

    @classmethod
    def _helper_script(cls) -> str:
        helper_functions = _render_loop_blocks(
            "\n".join(
                _function(cls.source, name)
                for name in (
                    "CheckInstallPayloadPaths",
                    "UninstallPreviousVersion",
                    "ValidatePreviousInstall",
                    "InvokePreviousUninstaller",
                    "VerifyPreviousUninstall",
                    "CheckSafeInstallPath",
                    "CheckNoReparsePoint",
                    "CheckAPEXProcesses",
                    "DetectAPEXProcess",
                )
            )
        )
        return (
            cls._preamble(cls.helper_installer)
            + '''\
Var PreviousUninstallMode
Var PreviousUninstallExitCode
Var PreviousInstallValidated
Var PreviousRunValue
Var PreviousMainBinaryName
Var TestResultPath
Function .onInit
  StrCpy $INSTDIR "$TEMP\\APEX_NSIS_TEST_'''
            + cls.identity
            + '''"
  ${GetOptions} $CMDLINE "/MODE=" $R8
  ${IfNot} ${Errors}
    StrCpy $PreviousUninstallMode $R8
  ${Else}
    StrCpy $PreviousUninstallMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/PASSIVE=" $R6
  ${IfNot} ${Errors}
    StrCpy $PassiveMode $R6
  ${EndIf}
  ${GetOptions} $CMDLINE "/RESULT=" $TestResultPath
  ${GetOptions} $CMDLINE "/ROOT=" $R7
  ${IfNot} ${Errors}
    StrCpy $INSTDIR $R7
  ${EndIf}
FunctionEnd
Section "Run production upgrade cleanup helper"
  Call CheckInstallPayloadPaths
  FileOpen $9 $TestResultPath w
  FileWrite $9 "preflight"
  FileClose $9
  Call UninstallPreviousVersion
  IfErrors nsis_test_cleanup_errors
  FileOpen $9 $TestResultPath w
  FileWrite $9 "preflight cleanup-complete"
  FileClose $9
  Goto nsis_test_cleanup_marked
nsis_test_cleanup_errors:
  FileOpen $9 $TestResultPath w
  FileWrite $9 "preflight cleanup-errors-remain"
  FileClose $9
nsis_test_cleanup_marked:
SectionEnd
'''
            + helper_functions
            + "\n"
        )

    @classmethod
    def _process_script(cls) -> str:
        return f'''\
Unicode true
OutFile "{str(cls.process_exe).replace(chr(92), chr(92) * 2)}"
SilentInstall silent
RequestExecutionLevel user
Section
  Sleep 45000
SectionEnd
'''

    @classmethod
    def _delete_test_registry(cls) -> None:
        import winreg

        errors: list[OSError] = []
        for key in (cls.test_key, cls.uninstall_key, cls.install_root, cls.manufacturer_key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except FileNotFoundError:
                pass
            except OSError as exc:
                errors.append(exc)
        try:
            run_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, cls.run_key, 0, winreg.KEY_SET_VALUE
            )
        except FileNotFoundError:
            run_key = None
        except OSError as exc:
            errors.append(exc)
            run_key = None
        if run_key is not None:
            with run_key:
                for value_name in (cls.product_name, cls.foreign_run_name):
                    try:
                        winreg.DeleteValue(run_key, value_name)
                    except FileNotFoundError:
                        pass
                    except OSError as exc:
                        errors.append(exc)
        if errors:
            raise errors[0]

    def setUp(self) -> None:
        self.root = self.base / f"install-{uuid.uuid4().hex[:8]}"
        self.data_dir = self.base / f"data-{uuid.uuid4().hex[:8]}"
        self.data_dir.mkdir()
        self.data_file = self.data_dir / "operator-data.db"
        self.data_file.write_text("keep", encoding="utf-8")
        self.result = self.base / f"result-{uuid.uuid4().hex[:8]}.txt"
        self._run_old_installer()
        (self.root / "operator.keep").write_text("keep", encoding="utf-8")

    def _run(self, executable: Path, args: list[str], *, timeout: int = 40) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(executable), *args],
            cwd=self.base,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    def _run_old_installer(self) -> None:
        result = self._run(self.old_installer, ["/S", f"/D={self.root}"])
        self.assertEqual(
            result.returncode,
            0,
            result.stdout + result.stderr,
        )
        self.assertTrue((self.root / "uninstall.exe").is_file())

    def _run_helper(self, mode: int = 1) -> subprocess.CompletedProcess[str]:
        args = ["/S", f"/MODE={mode}"]
        if mode == 0:
            args.append("/PASSIVE=1")
        return self._run(
            self.helper_installer,
            [*args, f"/RESULT={self.result}", f"/ROOT={self.root}"],
        )

    def _assert_old_payload_present(self) -> None:
        for path in ("apex-desktop.exe", *RESOURCE_FILES):
            self.assertTrue((self.root / Path(path)).is_file(), path)

    def _assert_registration(self, *, present: bool) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.uninstall_key) as key:
                value, _ = winreg.QueryValueEx(key, "UninstallString")
            found = bool(value)
        except FileNotFoundError:
            found = False
        self.assertEqual(found, present)

    def test_production_update_cleanup_removes_stale_metadata_and_preserves_operator_state(self) -> None:
        result = self._run_helper()
        self.assertEqual(
            result.returncode,
            0,
            f"{result.stdout}{result.stderr} marker={self.result.read_text() if self.result.exists() else 'missing'}",
        )
        self.assertEqual(self.result.read_text(encoding="utf-8"), "preflight cleanup-complete")
        self.assertFalse((self.root / "apex-desktop.exe").exists())
        for path in RESOURCE_FILES:
            self.assertFalse((self.root / Path(path)).exists(), path)
        self.assertTrue((self.root / "operator.keep").is_file())
        self.assertEqual(self.data_file.read_text(encoding="utf-8"), "keep")
        self._assert_registration(present=False)
        self.assertTrue((self.root / "uninstall.exe").is_file())
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.run_key) as key:
            startup, _ = winreg.QueryValueEx(key, self.product_name)
            foreign, _ = winreg.QueryValueEx(key, self.foreign_run_name)
        self.assertEqual(startup, f'"{self.root}\\apex-desktop.exe" --autostart')
        self.assertEqual(foreign, "foreign command")

    def test_verified_normal_uninstall_clears_expected_registry_error_flag(self) -> None:
        result = self._run_helper(mode=0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.result.read_text(encoding="utf-8"), "preflight cleanup-complete")
        self.assertFalse((self.root / "apex-desktop.exe").exists())
        self.assertTrue((self.root / "operator.keep").is_file())
        self.assertEqual(self.data_file.read_text(encoding="utf-8"), "keep")
        self._assert_registration(present=False)
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.run_key) as key:
            with self.assertRaises(FileNotFoundError):
                winreg.QueryValueEx(key, self.product_name)
            foreign, _ = winreg.QueryValueEx(key, self.foreign_run_name)
        self.assertEqual(foreign, "foreign command")

    def test_zero_exit_with_previous_shell_remaining_fails_verification(self) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.test_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "leave_shell", 0, winreg.REG_SZ, "yes")
        result = self._run_helper()
        self.assertEqual(self.result.read_text(encoding="utf-8"), "preflight")
        self.assertTrue((self.root / "apex-desktop.exe").is_file())
        self.assertTrue((self.root / "operator.keep").is_file())
        self.assertFalse((self.root / RESOURCE_FILES[0]).exists())
        self._assert_registration(present=False)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.test_key) as key:
            postuninstall, _ = winreg.QueryValueEx(key, "postuninstall")
        self.assertEqual(postuninstall, "completed")
        self.assertIn(result.returncode, (0, 1, 2), result.stdout + result.stderr)

    def test_actual_uninstall_section_removes_only_owned_startup_and_install_content(self) -> None:
        result = self._run(self.root / "uninstall.exe", ["/S", f"_?={self.root}"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "apex-desktop.exe").exists())
        for path in RESOURCE_FILES:
            self.assertFalse((self.root / Path(path)).exists(), path)
        self.assertTrue((self.root / "operator.keep").is_file())
        self.assertEqual(self.data_file.read_text(encoding="utf-8"), "keep")
        self._assert_registration(present=False)
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.run_key) as key:
                winreg.QueryValueEx(key, self.product_name)
        except FileNotFoundError:
            pass
        else:
            self.fail("normal uninstall retained the APEX-owned Run value")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.run_key) as key:
            foreign, _ = winreg.QueryValueEx(key, self.foreign_run_name)
        self.assertEqual(foreign, "foreign command")

    def test_malformed_registration_fails_before_removing_payload(self) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.uninstall_key) as key:
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, '"C:\\unsafe\\uninstall.exe"')
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "2.0.0")
            winreg.SetValueEx(key, "MainBinaryName", 0, winreg.REG_SZ, "apex-desktop.exe")
        result = self._run_helper()
        self.assertEqual(self.result.read_text(encoding="utf-8"), "preflight")
        self._assert_old_payload_present()
        self.assertIn(result.returncode, (0, 1, 2), result.stdout + result.stderr)

    def test_partial_ownership_markers_fail_before_removing_payload(self) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.install_root, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "")
        result = self._run_helper()
        self.assertEqual(self.result.read_text(encoding="utf-8"), "preflight")
        self._assert_old_payload_present()
        self._assert_registration(present=True)
        self.assertIn(result.returncode, (0, 1, 2), result.stdout + result.stderr)
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.test_key) as key:
            invoked, _ = winreg.QueryValueEx(key, "invoked")
        self.assertEqual(invoked, "")

    def test_current_only_destination_junction_fails_before_previous_cleanup(self) -> None:
        link = self.root / "current-only-resource"
        target = self.base / f"junction-target-{uuid.uuid4().hex[:8]}"
        target.mkdir()
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest(f"Windows could not create a test-owned junction: {result.stdout}{result.stderr}")
        self.addCleanup(lambda: link.rmdir() if link.exists() else None)
        result = self._run_helper()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.result.exists())
        self._assert_old_payload_present()
        self._assert_registration(present=True)
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.test_key) as key:
            invoked, _ = winreg.QueryValueEx(key, "invoked")
        self.assertEqual(invoked, "")

    def test_reparse_uninstaller_fails_before_running_previous_cleanup(self) -> None:
        uninstaller = self.root / "uninstall.exe"
        uninstaller.unlink()
        try:
            uninstaller.symlink_to(self.old_installer)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Windows symlink creation is unavailable: {exc}")
        result = self._run_helper()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.result.exists())
        self._assert_old_payload_present()
        self._assert_registration(present=True)
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.install_root) as key:
            saved_root, _ = winreg.QueryValueEx(key, "")
        self.assertEqual(saved_root, str(self.root))
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.test_key) as key:
            invoked, _ = winreg.QueryValueEx(key, "invoked")
        self.assertEqual(invoked, "")

    def test_running_apex_process_refuses_cleanup(self) -> None:
        process = subprocess.Popen([str(self.process_exe)], cwd=self.base)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                listed = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq APEX.exe", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if '"APEX.exe"' in listed.stdout:
                    break
                time.sleep(0.1)
            else:
                self.fail("synthetic APEX.exe process did not appear in tasklist")
            result = self._run_helper()
        finally:
            process.terminate()
            process.wait(timeout=10)
        self.assertEqual(self.result.read_text(encoding="utf-8"), "preflight")
        self._assert_old_payload_present()
        self.assertIn(result.returncode, (0, 1, 2), result.stdout + result.stderr)

    def test_nonzero_prior_uninstaller_exit_blocks_current_payload(self) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.test_key) as key:
            winreg.SetValueEx(key, "failure", 0, winreg.REG_SZ, "nonzero")
        result = self._run_helper()
        self.assertEqual(self.result.read_text(encoding="utf-8"), "preflight")
        self._assert_old_payload_present()
        self._assert_registration(present=True)
        self.assertIn(result.returncode, (0, 1, 2, 37), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
