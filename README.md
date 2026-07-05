# Custom Program Launcher

A lightweight Windows app for launching a sequence of programs, each with its own configurable delay: handy for firing up your whole streaming, gaming, or work setup with a single click instead of opening everything by hand.

![Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![License](https://img.shields.io/badge/license-MPL--2.0-orange)

![Custom Program Launcher screenshot](https://github.com/Vulkandr/custom-program-launcher/blob/main/screenshot.png?raw=true)

## Features

- **Add programs two ways:** pick from a list of your installed programs, or browse to any `.exe`/`.lnk` manually through the file browser
- **Configurable delay per program:** after each program launches, it waits your chosen number of seconds (giving it time to boot) before moving to the next one
- **Multiple named lists:** save different setups (e.g. "Streaming," "Gaming," "Work") and switch between them instantly
- **Matches Windows light and dark mode**
- **Remembers your lists and settings between sessions**
- **Settings menu**
  - *Open on Startup:* launches with Windows (cleanly reversible, just a registry entry)
  - *Close After Launch All:* auto-closes once every program has been launched
  - *Default Delay:* set what new programs pre-fill with, instead of always retyping the same number

## Download

Grab the latest release from the [Releases page](https://github.com/Vulkandr/custom-program-launcher/releases/latest).

## Usage

1. Open the app and click **Choose Installed Program** or **Browse for File...** to add a program
2. Set the delay (in seconds) for how long it should wait after that program launches before moving to the next one
3. Reorder with **Move Up** / **Move Down** if needed
4. Click **Launch All** to fire off the whole sequence
5. Use **New List** / **Duplicate As...** / **Rename** / **Delete List** to manage multiple setups
6. Click **Settings** (top right) for startup/auto-close options and to set your preferred default delay when adding a new program

## License

Licensed under the [Mozilla Public License 2.0](LICENSE). In short: you're free to use, modify, and distribute this software (including in closed-source/commercial projects), but if you modify any of the actual source files from this project and distribute them, those modified files must stay under MPL 2.0 and their source made available. See the [LICENSE](LICENSE) file for the full terms.

---

Want to build this yourself? See [How to Compile Yourself.txt](<How to Compile Yourself.txt>).
