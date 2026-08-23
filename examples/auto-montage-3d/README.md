# Synthetic Beat3D input fixture

This example commits no third-party media. The generator creates four local
FFmpeg test clips, an eight-second 120 BPM click track, and a short brief.

```bash
python examples/auto-montage-3d/create_demo_inputs.py /tmp/openmontage-beat3d-demo
.venv/bin/openmontage init /tmp/openmontage-beat3d-demo --slug beat3d-demo
```

On Windows PowerShell, replace the second command with:

```powershell
.venv\Scripts\openmontage.exe init "$env:TEMP\openmontage-beat3d-demo" --slug beat3d-demo
```

The generator refuses to overwrite a non-empty directory.
