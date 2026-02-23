# AMD GPU Monitor (Ubuntu)

Desktop app for live AMD GPU monitoring on Ubuntu using `amd-smi`.

## Features

- Select GPU index (`-g N`)
- Update interval dropdown (`1` to `10` seconds)
- Live line charts (GPU util, memory util, hotspot temp, memory temp, power, VRAM used, GPU clock)
- Rolling history window selector (`60/120/300/600` seconds)
- `Sample Now` and `Clear` buttons

## Requirements

- Ubuntu with AMD SMI installed (`amd-smi` command available)
- Python 3
- Tkinter (`python3-tk` package on Ubuntu)

Install Tkinter if needed:

```bash
sudo apt install python3-tk
```

## Run

```bash
python3 amdmon.py
```

Or run it directly (the script already includes a Python shebang):

```bash
chmod +x amdmon.py
./amdmon.py
```

## Add `amdmon` to your PATH (symlink)

If you want to run it with a shorter command (`amdmon`) without a wrapper script, create a symlink in a directory that is already on your `PATH` (for example `~/.local/bin`).

Create the directory if needed:

```bash
mkdir -p ~/.local/bin
```

Create the symlink:

```bash
ln -sf /home/crosson/git/amdmon/amdmon.py ~/.local/bin/amdmon
chmod +x /home/crosson/git/amdmon/amdmon.py
```

Then run:

```bash
amdmon
```

If `amdmon` is not found, make sure `~/.local/bin` is in your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## Notes

- GPU index maps directly to `amd-smi monitor -g <index> --json`.
- If you use `-g 0` for your `r9700 pro`, set GPU Index to `0` in the app.
- Errors from `amd-smi` are shown in the UI so you can quickly spot invalid GPU indexes or missing permissions.
