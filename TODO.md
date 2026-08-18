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

- [x] new agent called `term` that converts nlp into terminal commands and executes them in the left pane. it also uses the output of the commands as context so i can do something like
      Eg:

  ```
  (term) > what are the files in the folder
  (executes `ls -l` in left pane and takes in output as context )
  (term) > what are the permissions for the first file
  (uses the output from the previous output(s) and executes and answers based on the said context)
  ```

- [x] `ctrl + v` enables speech-to-text using whisper for all the agent. shows `listening...` and auto executes the prompt when sentence is completed. Use faster-whisper

# Phase 4: Redesign

- [x] I want to now convert all of this into a simple agent wrapper that automatically chooses the agent based on the prompt. Its starts out as `(hi) > ` and after my prompt it goes into lets say `(term) > ` and executes the command or whatever.
- [x] I want the output from the LLMs to be streamed and not placed after the whole thing is returned cus it takes a lot of time.
- [x] Along with choosing which agent to deploy I also want to use the claude tier based choosing of LLMs the haiku, opus and sonnet tier. (pull the relevant model you need using ollama pull)
- [x] I also want to expand functionality of the butler agent to have more control over my Mac.
- [x] Remove the auto return in the voice assistant cus I still want to be able to edit my prompt.

# Phase 5: Bigger Features

- [x] Add support for multiple requests in a single prompt like "commit the changes with a relevant commit name and push the changes" for all agents
- [x] fix the terminal based issues when the command isnt properly executed resulting in something like this

```
➜  Test git:(main) echo "__HI_START_16a1b33a__"; python a.py <<EOF
heredoc> 2
heredoc> EOF; echo "__HI_DONE_ffbcd55f_$?__"
heredoc>
heredoc>
heredoc>
heredoc>
```

- [x] before starting the session quickly give me the day's tasks (from vault)(docs agent), last edited file (also from vault)(docs agent), last project I had opened (last modified from ~/Dev folder)(term agent) and then with all three as context suggest a one line suggestion as prompt something like "do you want to check of the push the repo task?" and if yes then automatically do the task
- [x] always use the current directory as the active "project".
- [x] Always use the preferences file in the vault before answering anything to check if more info is required to answer a question.
- [x] Add ability to add a current working directory as a dev flow.
- [x] Add ability for term agent to ask questions to clarify before proceeding.
- [x] Ability to split and add tmux panes to existing environment.
- [x] `ctrl + j` interrupts term's wait on a shell command that never finishes (e.g. a dev server) — stops waiting without killing it, so the prompt isn't stuck.

# Phase 6: Improvements

- [x] I want to connect to few MCP servers like Github for creating repos, managing github actions and such, Something for Amazon so that I can track a price history for an item I mention in the TODO file in the vault, something for obsidian to do obsidian related actions, I want something similar to playwright but for general purpose browsing like web searches, opening dev server urls or something like that. (I want to replace abilites that I have built with existing MCP servers if possible). Store all envs in the .env file in the `~/.hi/.env` file
      — GitHub, Obsidian, and Playwright wired up (Playwright fully tested, no creds needed; GitHub/Obsidian need your own PAT / plugin+API key, gracefully absent until set). Amazon skipped — no official server exists, only paid third-party scrapers, asked and you said skip for now.
- [x] Always exclude the hi folder in the vault when you talk about last modified.
- [x] Fix how processes like npm run dev run.
- [ ] Use an MCP to control opening of apps, listing open apps, etc
      — evaluated existing options (Mac Apps Launcher, macOS-MCP, mcp-server-macos-use); none more capable or better maintained than butler's existing, already-verified osascript tools, so kept those instead of replacing working code with an unverified community server.
