# Implement the Memory System (MVP)

## Context

You are working on an AI assistant that uses **Ollama**, **LangChain**, and **LangGraph**.

The philosophy of the project is:

- The filesystem is the **single source of truth**.
- The LLM should never store memory internally.
- Everything important should eventually exist as Markdown files.
- Keep the implementation simple and easy to extend.
- Prefer clean, modular code over unnecessary abstractions.

## Goal

Implement a minimal memory system that allows the agent to organize information into Markdown files.

This is **not** a vector database or RAG implementation. Ignore embeddings, indexing, databases, and long-term memory for now.

## Directory Structure

Create the following structure if it does not already exist.

```text
memory/
├── conversations/
└── knowledge/
```

## Features

### 1. Conversation Logging

Every interaction between the user and assistant should be appended to a Markdown file inside:

```text
memory/conversations/
```

Use a sensible filename (for example based on the current date).

Format is up to you, but it should remain readable by humans.

---

### 2. Knowledge Files

Inside

```text
memory/knowledge/
```

the agent should be able to create and update Markdown notes.

The organization should be determined by the model when appropriate.

Examples:

```text
memory/knowledge/projects/kaapi.md
memory/knowledge/preferences.md
memory/knowledge/ideas.md
```

Do not hardcode categories beyond providing the base `knowledge/` directory.

---

### 3. Filesystem Tools

Implement tools that allow the agent to interact with the filesystem.

At minimum:

- create a note
- append to a note
- read a note
- list existing notes

These tools should perform all filesystem operations.

---

### 4. LangGraph Agent

Create a LangGraph ReAct agent using the existing Ollama model.

The agent should:

- use the filesystem tools
- answer user questions normally
- create or update notes whenever the user explicitly asks it to remember, organize, or save information

Keep the graph simple.

---

## Requirements

- Use Python.
- Use LangChain.
- Use LangGraph.
- Use Ollama for the model.
- Use pathlib for filesystem operations.
- Keep functions small and readable.
- Add type hints where appropriate.
- Avoid overengineering.
- Avoid unnecessary classes unless they improve readability.

## Do NOT Implement

Do not add:

- embeddings
- vector databases
- MongoDB
- FAISS
- Chroma
- semantic search
- memory extraction agents
- reflection agents
- background jobs
- asynchronous processing
- databases
- caching

Those will be added later.

## Deliverable

Produce a clean, modular implementation that is easy to extend in future iterations while keeping the current MVP as small as possible.
