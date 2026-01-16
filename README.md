# ANT+ Heart Rate Monitor

Desktop application for monitoring ANT+ heart rate sensors with a clean, always-on-top overlay mode.

## Features

- 🏃 Real-time heart rate monitoring from ANT+ devices (watches, chest straps)
- 📍 Always stays on top of other windows
- 🎨 Transparent overlay mode (press 'O')
- 🖱️ Drag anywhere to move
- ⌨️ Keyboard shortcuts

## Installation & Usage

### Quick Start with uvx (recommended)

```bash
uvx --from . antmonitor
```

Or install and run:

```bash
pip install .
antmonitor
```

### Development Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode
pip install -e .

# Run the application
antmonitor
```

## Requirements

- Python 3.9+
- ANT+ USB dongle (e.g., Garmin AP2USB1.05)
- ANT+ heart rate monitor (watch or chest strap)
- macOS/Linux: libusb (`brew install libusb` or `apt install libusb-1.0-0`)

## Keyboard Shortcuts

- **O** - Toggle transparent overlay mode
- **Esc** - Exit overlay mode
- **Click & Drag** - Move window anywhere

## First Time Setup

1. Plug in your ANT+ USB dongle
2. Turn on your heart rate monitor and start an activity
3. Run the app - it will automatically connect to device #42687
4. If you need to find your device ID:
   ```bash
   python -m openant scan --device_type HeartRate --auto_create
   ```
   Then update the `device_id` in `antmonitor/main.py`

## Troubleshooting

**Window hangs or freezes:**
- The app uses background threading to prevent UI freezes

**No heart rate data:**
- Ensure your heart rate monitor is actively broadcasting (start a workout)
- Check that the ANT+ dongle is connected
- Use `openant scan` to verify your device ID

**Permission errors (Linux):**
```bash
sudo usermod -a -G plugdev $USER
# Then log out and back in
```

## License

MIT
