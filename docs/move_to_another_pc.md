# Move This Project To Another PC

This project is now intended to run from a Windows working copy. The easiest way to move it is:

1. Export the current working tree from the source PC.
2. Extract it on the destination PC.
3. Recreate `.venv` on the destination PC.

## Export From The Source PC

Run this from the repo root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_for_pc_move.ps1
```

By default, the script:

- creates a zip under `output\transfer\`
- includes the current repo contents, including `.git`
- includes `data\` and `booklets\` if they exist
- excludes `.venv`, caches, `build\`, `dist\`, and `tmp\`
- excludes `output\` to keep the archive smaller
- includes `%APPDATA%\ReportGen\templates\報告書_ひな形_v2.docx` if it exists

Useful options:

```powershell
# Include generated output files too
powershell -ExecutionPolicy Bypass -File .\scripts\export_for_pc_move.ps1 -IncludeOutput

# Create the zip somewhere else
powershell -ExecutionPolicy Bypass -File .\scripts\export_for_pc_move.ps1 -OutDir D:\transfer

# Exclude .git metadata if you only want the files
powershell -ExecutionPolicy Bypass -File .\scripts\export_for_pc_move.ps1 -SkipGit
```

The archive also contains:

- `migration_assets\MIGRATE_TO_NEW_PC.txt`
- `migration_assets\manifest.json`

## Restore On The Destination PC

1. Extract the zip to a normal Windows folder.
2. If the archive contains `migration_assets\appdata\ReportGen\templates\報告書_ひな形_v2.docx`, copy it to:
   `%APPDATA%\ReportGen\templates\`
3. Open PowerShell in the extracted repo root and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_on_new_pc.ps1
```

4. Verify the environment:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_on_new_pc.ps1 -RunTests -CompareSamples -SmokeGui
powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -RunGui"
```

If you do not want to restore the bundled `%APPDATA%` template, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_on_new_pc.ps1 -RestoreAppDataTemplate:$false
```

## Environment Variables To Reapply If Needed

- `OPENAI_API_KEY`
- `REPORTGEN_TEMPLATE_PATH`
- `REPORTGEN_OUT_DIR`
- `REPORTGEN_BOOKLET_INDEX`
- `REPORTGEN_BOOKLET_OUTDIR`
- `REPORTGEN_BOOKLET_CANDIDATES`
- `REPORTGEN_BOOKLET_BUFFER`
- `REPORTGEN_BOOKLET_CODE_FIELD`
- `REPORTGEN_BOOKLET_NAME_FIELD`
- `REPORTGEN_AI_MODEL`

## Notes

- If you want a full working copy with history and local branches, keep the default behavior and include `.git`.
- Do not copy `.venv` from the old PC. Recreate it with `build_win.ps1`.
- If you later decide to use Git as the main handoff path, this script is still useful for the ignored local assets like `data\` and `booklets\`.
