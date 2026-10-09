
## Development hot reload

For development, use the Gradio CLI rather than `python app.py`. The CLI watches the project and reloads the interface after Python or UI changes:

```bash
cd "/mnt/d/Medical-Assitant-Fixed"
conda activate KEMsrag
gradio app.py
```

From PowerShell, run:

```powershell
.\run_dev.ps1
```

The repository also includes `run_dev.sh` for WSL. Stop the watcher with `Ctrl+C`. Use `python app.py` when you want a normal non-reloading process.
