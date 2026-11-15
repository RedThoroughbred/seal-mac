<p align="center"><img src=".claude-plugin/icon.png" width="96" alt="Seal"></p>

# Seal for Mac

**Lock your Claude Code sessions until your iPhone says yes with Face ID. Sign your git commits with your phone.**

This is the Mac side of [Seal](https://redthoroughbred.github.io/seal), an iPhone app that keeps a signing key in the phone's Secure Enclave. Nothing on your Mac can make that key's signatures, so nothing on your Mac can open the lock by itself: not a script, not an agent, not someone who got into your account.

```
/plugin marketplace add RedThoroughbred/seal-mac
/plugin install seal@seal-mac
```

You need Seal on your iPhone, a Mac with Claude Code, and Python 3 (Claude Code users nearly always have it). The phone and the Mac hand the request and the answer over the shared clipboard: the same Apple Account on both, Handoff on, the phone near the Mac.

## Pair your phone (once)

1. On the phone: Seal, **Sign** page, `Copy SSH key`.
2. In Claude Code: `/seal:pair`

The Mac now trusts that one key, and only it.

## Lock your sessions

```
/seal:on
```

From your next message, every Claude Code session on this Mac takes no message and runs no tool until your phone signs a **pass**:

1. Your message is held, and a request is put on the clipboard.
2. On the phone: **Sign**, `Paste a signing request`. It names your Mac and when the pass ends. `Sign with Face ID`, `Copy the signature`.
3. Send your message again. The pass is good for 30 minutes, for every session on this Mac.

| Command | What it does |
| --- | --- |
| `/seal:status` | Whether the lock is on, whether a pass is good and until when, which phone key is paired |
| `/seal:pass 120` | Ask for a longer pass now (30 minutes unless you say, 4 hours at most) |
| `/seal:drop` | End the pass now: everything locks again |
| `/seal:off` | Turn the lock off. **This needs your phone too**: a yes signed for exactly "Turn the Seal lock off" |
| `/seal:pair` | Pair a phone. Refused while the lock is on |
| `/seal:git` | Sign this repository's commits with your phone |

While a session is locked, `/seal:status`, `/seal:on`, `/seal:off`, `/seal:drop` and `/seal:pass` still go through, typed alone. None of them opens anything. Claude can't run any of these commands itself.

**Away from the Mac,** with Remote Control on your phone: the held message shows the request as one `seal://sign?…` line. Copy it into Seal, sign, and paste the signature back as your next message. That works for a pass and for `/seal:off`.

## Sign git commits

Inside a repository: `/seal:git`. Then `git commit -S`, or `git config commit.gpgsign true` to sign every commit there.

When git wants a signature, the request goes on the clipboard (with a notice on the Mac when an agent ran git). Sign it on the phone and `Copy the signature`: git picks it up from the clipboard, checks it with `ssh-keygen` against your key, and only then signs. In a terminal you can also paste it. Add the same key to GitHub as a **Signing Key** and the commits show as Verified.

## What it holds and what it doesn't

- It holds messages and tool calls in every Claude Code session that loads your settings, the one you're in included.
- While a pass is good, sessions work as usual, with Claude's own permission questions.
- A pass, a yes to one command, a commit signature and a yes to turning the lock off are four different purposes. A signature made for one never counts as another, and a yes counts once.
- If the lock breaks or can't start while it's on, it holds (`"onFailure": "block"`). While it's off, it doesn't start Python at all.
- The lock's files (`~/.seal-gate`) belong to your user account. While a pass is good, an agent determined to remove the lock could. A version with its rules in an admin-owned file, which no agent can change, is planned.
- A command typed with `!` at the Mac's own keyboard runs without hooks. Whoever sits at your keyboard can open Terminal anyway; from the phone, a `!` line arrives as a plain message, and is held.
- A session started with your settings left out (`claude --setting-sources ""`) isn't under the lock. That is how a scheduled job stays out of it. The lock keeps your agents from being driven by someone else; it doesn't stop someone who can already run commands on your Mac.
- It talks to no network. Signatures are checked by the Mac's own `ssh-keygen`.

## Without the plugin

The tools in `bin/` also run by hand: `bin/seal-gate --help` and `bin/seal-git-sign --help`. To lock one session only: `claude --settings "$(bin/seal-gate settings)"`.

## Tests

```
python3 -m unittest discover -s tests -v
```

They run the real tools and the real `ssh-keygen` with a stand-in phone key and a pretend clipboard, in a temporary folder: your `~/.seal-gate` and clipboard are never touched.

## License

MIT. Seal's iPhone app is a separate, closed product.
