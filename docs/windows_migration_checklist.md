# Windows Complete Migration Checklist

This project should be operated from the Windows working copy only:

- `C:\Users\entor\Documents\030.work\101.pdf2doc\reportgen_v1`

Do not use the WSL-side alias path as the primary workspace after this migration:

- `/home/entora777/workspace_pdf2doc/reportgen_v1`

## 1. Source Of Truth

- [ ] Confirm the canonical repo path is `C:\Users\entor\Documents\030.work\101.pdf2doc\reportgen_v1`
- [ ] Open the repo in IDE from the Windows path, not from `/home/...`
- [ ] Confirm `git status` is run from the Windows repo root
- [ ] Confirm all current uncommitted changes are intentional before further cleanup

## 2. Python Runtime

- [ ] Confirm Windows Python is available: `py -3 --version`
- [ ] Recreate the virtualenv if needed:
  - `powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -RecreateVenv -InstallDeps"`
- [ ] Confirm the virtualenv is Windows-style:
  - `.venv\Scripts\python.exe` exists
  - `.venv\bin\python` does not exist
- [ ] Confirm editable install works:
  - `powershell -ExecutionPolicy Bypass -Command "& '.\.venv\Scripts\python.exe' -c \"import reportgen\""`

## 3. App Verification

- [ ] Run tests:
  - `powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -RunTests"`
- [ ] Run sample comparison once:
  - `powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -CompareSamples"`
- [ ] Confirm `data/samples/05-10` match expected DOCX outputs
- [ ] Confirm GUI import works:
  - `powershell -ExecutionPolicy Bypass -Command "& '.\.venv\Scripts\python.exe' -c \"import reportgen.gui.app\""`
- [ ] Run GUI smoke test:
  - `powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -SmokeGui"`
- [ ] Launch GUI once from Windows:
  - `powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -RunGui"`
- [ ] Generate one sample report from real input and confirm output opens correctly in Word

## 4. IDE And Tooling

- [ ] In VS Code, select interpreter:
  - `C:\Users\entor\Documents\030.work\101.pdf2doc\reportgen_v1\.venv\Scripts\python.exe`
- [ ] Disable any auto-open behavior that reopens the repo through WSL
- [ ] Confirm terminal inside IDE starts in the Windows repo path
- [ ] Confirm search, run, and debug tasks use the Windows interpreter

## 5. Data And File Handling

- [ ] Confirm drag-and-drop paths from Explorer resolve correctly in the GUI
- [ ] Confirm output folders are created under the Windows repo, not under WSL-only paths
- [ ] Confirm template discovery still works from the Windows filesystem
- [ ] Confirm there is no second active working copy being edited elsewhere

## 6. WSL Cleanup Preconditions

Only remove WSL-side conveniences after all checks above pass.

- [ ] Confirm no active shell, IDE, or automation still depends on `/home/entora777/workspace_pdf2doc`
- [ ] Confirm there are no cron/jobs/scripts that call the repo through WSL
- [ ] Confirm backup or Git commit exists before destructive cleanup

## 7. WSL Cleanup Actions

If the `/home/...` path is only a symlink alias, remove just the alias:

- [ ] `rm /home/entora777/workspace_pdf2doc`

If you want to stop using this WSL distro entirely, do that only after Windows-side verification is complete:

- [ ] Export anything else you still need from WSL
- [ ] Run `wsl --list --verbose` from Windows
- [ ] Unregister the target distro only if this repo is no longer needed there:
  - `wsl --unregister <DistroName>`

## 8. Rollback Rule

Stop cleanup and keep the WSL alias if any of the following fail:

- [ ] GUI launch from Windows
- [ ] Test execution from Windows
- [ ] Real report generation from Windows
- [ ] IDE interpreter/debugger integration on Windows

If a rollback is needed:

- [ ] Restore the previous access path first
- [ ] Do not delete the WSL alias or distro yet
- [ ] Fix the failing Windows-side step and re-run this checklist

## 9. Done Definition

Migration is complete only when all of the following are true:

- [ ] Development is done from `C:\...`
- [ ] `.venv` is Windows-native
- [ ] Tests pass on Windows
- [ ] GUI runs on Windows
- [ ] One real report is generated on Windows
- [ ] No daily workflow depends on `/home/...`
