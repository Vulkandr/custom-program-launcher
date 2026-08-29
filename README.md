# Custom Program Launcher

A lightweight Windows app for launching a sequence of programs and scripts, each with its own timing and startup behavior: handy for firing up your whole streaming, gaming, or work setup with a single click instead of opening everything by hand.

![Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![License](https://img.shields.io/badge/license-MPL--2.0-orange)

![Custom Program Launcher screenshot](https://github.com/Vulkandr/custom-program-launcher/blob/main/screenshot.png?raw=true)

## Features

- **Add things three ways:** pick from a list of your installed programs, browse to any file through the file browser, or write a PowerShell or Command Prompt script to run directly
- **Control the timing per item:** continue immediately, wait a set number of seconds, wait until the program's window appears, or wait for the window and then a few extra seconds
- **Control how each program starts:** normally, minimized to the taskbar, or with its window closed (which sends apps like Discord straight to the system tray)
- **Command-line arguments per program**
- **Multiple named lists:** save different setups (e.g. "Streaming," "Gaming," "Work") and switch between them instantly
- **Auto-launch on startup:** mark a list to launch automatically when Windows starts, with a 5 second countdown you can cancel before it runs
- **Drag and drop to reorder**, and right-click any item to launch just that one, rename it, duplicate it, or open its folder
- **Matches Windows light and dark mode**
- **Remembers your lists and settings between sessions**

## Download

Grab the latest release from the [Releases page](https://github.com/Vulkandr/custom-program-launcher/releases/latest).

## Usage

1. Add something with **Choose Program**, **Browse for File...**, or **Add Script...**
2. Set its Launch Options: arguments, how long to wait before continuing, and how the program should start
3. Drag items to reorder them, or use **Move Up** / **Move Down**
4. Click **Launch All** to fire off the whole sequence
5. Right-click any item to launch just that one, which is a quick way to test a script
6. Use **New List** / **Duplicate As...** / **Rename** / **Delete List** to manage multiple setups
7. Check **Auto-launch on startup** (top left) to have the selected list launch automatically when Windows starts (requires *Open on Startup* to be enabled in Settings)
8. Open **Settings** (top right) for startup options, auto-close after launching, and your preferred default delay for new items

## License

Licensed under the [Mozilla Public License 2.0](LICENSE). In short: you're free to use, modify, and distribute this software (including in closed-source/commercial projects), but if you modify any of the actual source files from this project and distribute them, those modified files must stay under MPL 2.0 and their source made available. See the [LICENSE](LICENSE) file for the full terms.

---

Want to build this yourself? See [How to Compile Yourself.txt](<How to Compile Yourself.txt>).
