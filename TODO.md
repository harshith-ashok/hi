# Phase 1: Convert `docs` to obsidian helper

- [x] Use the vault for the docs helper as the path given in the ~/.hi/.env `VAULT_PATH` variable
- [x] Store every conversation inside the said vault irrespective of the role (`docs`, `code`, `web`,`butler`)
- [x] store conversations in obsidian compatible format inside a folder called hi/conversations in the vault and a custom tag called hi
- [x] store knowledge inside hi/knowledge/...
- [x] Properly integrate the obsidian vault so that any questions asked only gives me grounded answers from the md files. use the tags mentioned in each file as the keyword or look at the title of the note to identify the context of each note. Example: 'How does docker work? -> check for files with either title or tag as docker -> go through the file and cite or summarize'.
- [x] Go through tree cache as one of the sources for the file structure. See Phase 2 for more info

# Phase 2: Tweaks

- [x] Tree cache is basically `tree -L 4` executed in the vault directory and the output is stored in `~/.hi/tree_cache.md` file.
- [x] Fix tmux window splitting and session opening in `dev_flows`
- [x] movie the models used for each mode and move it to `~/.hi/,env`

# Phase 3: Addons

- [x] I want the `butler` agent to use the existing vault `hi` folder to create, delete and check off tasks from the TODO file start conversation with the items pending in the TODO:
      Eg:

```
      Today's Tasks:
  1. Buy Milk
  2. Fix something
     (butler) >

```
