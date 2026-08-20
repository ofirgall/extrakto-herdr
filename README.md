# extrakto-herdr

Extract text tokens from the focused [Herdr](https://herdr.dev) pane and fuzzy-pick them with [fzf](https://github.com/junegunn/fzf).

Inspired by [extrakto for tmux](https://github.com/laktak/extrakto) by [@laktak](https://github.com/laktak).

## Features

- Extract paths, URLs, words, lines, quoted strings from pane content
- Fuzzy-find with fzf
- Copy to clipboard (`enter`) or insert into pane (`tab`)
- Cycle through filter modes with `ctrl-f`
- Compatible with extrakto's user filter config (`~/.config/extrakto/extrakto.conf`)

## Requirements

- Python 3.6+
- [fzf](https://github.com/junegunn/fzf)

## Install

```bash
herdr plugin install ofirgall/extrakto-herdr
```

## Keybinding

Add to `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "ctrl+space"
type = "plugin_action"
command = "extrakto-herdr.open"
```

## Usage

1. Press your keybinding (e.g. `Ctrl+Space`)
2. Fuzzy-find the token you want
3. Press `enter` to copy to clipboard, or `tab` to insert into the pane
4. Press `ctrl-f` to cycle filter modes (all → word → path → url → line → quote)
5. Press `esc` to cancel

## Custom Filters

Create `~/.config/extrakto/extrakto.conf` (same format as the tmux plugin):

```ini
[my-filter]
regex: (my-custom-pattern)
min_length: 3
```

## Credits

This plugin is a port of [extrakto](https://github.com/laktak/extrakto) for the Herdr terminal workspace manager. All credit for the original concept, filter patterns, and UX goes to [@laktak](https://github.com/laktak) and the extrakto contributors.

## License

MIT
