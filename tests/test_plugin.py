"""Tests for the Seal plugin's Mac side: the switch, the door, /seal:off, pairing and git signing.

Everything runs for real: the tools in bin/, the real ssh-keygen as the judge, and a stand-in phone
(an ECDSA P-256 key, the kind the phone's Secure Enclave makes) that signs the way the app does. The
clipboard is a file, and the tools' folders live in a fresh temporary folder: nothing touches the real
~/.seal-gate or the real clipboard.

    python3 -m unittest discover -s tests -v
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE = os.path.join(ROOT, "bin", "seal-gate")
DOOR = os.path.join(ROOT, "bin", "seal-hook")
SSH_KEYGEN = "/usr/bin/ssh-keygen"


class Phone:
    """A stand-in for the phone's key. It signs like Seal's Sign page: SSH signatures, one purpose each."""

    def __init__(self, folder, name):
        self.path = os.path.join(folder, name)
        subprocess.run([SSH_KEYGEN, "-q", "-t", "ecdsa", "-b", "256", "-N", "", "-C", f"Seal on {name}", "-f", self.path], check=True)
        with open(self.path + ".pub") as handle:
            self.line = handle.read().strip()

    def sign(self, message, purpose):
        done = subprocess.run([SSH_KEYGEN, "-q", "-Y", "sign", "-f", self.path, "-n", purpose], input=message, capture_output=True, check=True)
        return done.stdout.decode()


def read_request(line):
    """What the phone reads from a seal:// line: the purpose and the words to sign."""
    found = re.search(r"seal://sign\?v=1&ns=([a-z-]+)&m=([A-Za-z0-9_-]+)", line)
    assert found, f"no request in: {line!r}"
    packed = found.group(2)
    return found.group(1), base64.urlsafe_b64decode(packed + "=" * (-len(packed) % 4))


class SealTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="seal-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.state = os.path.join(self.folder, "state")
        self.clip = os.path.join(self.folder, "clipboard")
        copy, paste = os.path.join(self.folder, "copy"), os.path.join(self.folder, "paste")
        with open(copy, "w") as handle:
            handle.write(f'#!/bin/sh\ncat > "{self.clip}"\n')
        with open(paste, "w") as handle:
            handle.write(f'#!/bin/sh\ncat "{self.clip}" 2>/dev/null\n')
        os.chmod(copy, 0o755)
        os.chmod(paste, 0o755)
        self.env = dict(os.environ, SEAL_GATE_DIR=self.state, SEAL_GATE_COPY=copy, SEAL_GATE_PASTE=paste,
                        SEAL_SIGN_DIR=os.path.join(self.folder, "sign"), SEAL_SIGN_NOTIFY="0", SEAL_SIGN_WAIT="20")
        self.phone = Phone(self.folder, "phone")

    # the parts

    def copy(self, text):
        with open(self.clip, "w") as handle:
            handle.write(text)

    def copied(self):
        try:
            with open(self.clip) as handle:
                return handle.read()
        except FileNotFoundError:
            return ""

    def run_tool(self, arguments, given=None, env=None, cwd=None):
        done = subprocess.run(["python3", GATE] + arguments, input=(given or "").encode(), capture_output=True,
                              env=env or self.env, cwd=cwd or self.folder, timeout=60)
        return done.returncode, done.stdout.decode(), done.stderr.decode()

    def slash(self, *words, cwd=None):
        return self.run_tool(["slash", *words], cwd=cwd)

    def door(self, event, env=None):
        """The plugin's hook, called the way Claude Code calls it: through sh and seal-hook."""
        done = subprocess.run(["sh", DOOR], input=json.dumps(event).encode(), capture_output=True,
                              env=env or self.env, cwd=self.folder, timeout=60)
        return done.returncode, done.stdout.decode(), done.stderr.decode()

    def message(self, words):
        return {"hook_event_name": "UserPromptSubmit", "prompt": words, "session_id": "s", "cwd": self.folder}

    def tool(self):
        return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "s", "cwd": self.folder}

    def paired(self):
        self.copy(self.phone.line + "\n")
        status, out, err = self.slash("pair")
        self.assertEqual(status, 0, out + err)

    def locked(self):
        self.paired()
        status, out, err = self.slash("on")
        self.assertEqual(status, 0, out + err)

    def answer_waiting_request(self, by=None, purpose=None):
        """The phone's part: read the request on the clipboard, sign it, copy the signature."""
        wanted, words = read_request(self.copied())
        self.copy((by or self.phone).sign(words, purpose or wanted))
        return wanted, words

    def lock_is_on(self):
        return os.path.exists(os.path.join(self.state, "lock-on"))


class TheSwitch(SealTestCase):
    def test_off_by_default_the_door_lets_everything_through_without_python(self):
        for event in (self.message("hello"), self.tool()):
            self.assertEqual(self.door(event)[0], 0)
        # No Python on the path: while the lock is off, the door does not need it.
        bare = dict(self.env, PATH="/nonexistent")
        self.assertEqual(subprocess.run(["/bin/sh", DOOR], input=b"{}", env=bare, capture_output=True).returncode, 0)

    def test_on_needs_a_paired_phone(self):
        status, out, _ = self.slash("on")
        self.assertEqual(status, 1)
        self.assertIn("Pair your phone first", out)
        self.assertFalse(self.lock_is_on())

    def test_on_holds_every_message_and_every_tool(self):
        self.locked()
        for event in (self.message("hello"), self.tool()):
            status, _, err = self.door(event)
            self.assertEqual(status, 2, err)
        self.assertIn("seal://sign?v=1&ns=seal-pass", self.copied(), "the pass request is on the clipboard")

    def test_when_the_lock_cannot_start_the_door_does_not_say_go(self):
        self.locked()
        bare = dict(self.env, PATH="/nonexistent")
        status = subprocess.run(["/bin/sh", DOOR], input=json.dumps(self.tool()).encode(), env=bare, capture_output=True).returncode
        self.assertNotIn(status, (0,), "without Python the hook fails, and onFailure: block holds")

    def test_a_pass_from_the_phone_opens_it_and_drop_locks_again(self):
        self.locked()
        self.assertEqual(self.door(self.message("hello"))[0], 2)
        purpose, words = self.answer_waiting_request()
        self.assertEqual(purpose, "seal-pass")
        self.assertIn(b"Seal session pass, version 1", words)
        self.assertEqual(self.door(self.message("hello again"))[0], 0)
        self.assertEqual(self.door(self.tool())[0], 0)
        self.assertEqual(self.slash("drop")[0], 0)
        self.assertEqual(self.door(self.tool())[0], 2)

    def test_pass_minutes_asks_for_that_length(self):
        self.locked()
        status, out, err = self.slash("pass", "120")
        self.assertEqual(status, 0, out + err)
        _, words = read_request(self.copied())
        self.assertIn(b"For: 2 hours", words)
        self.assertIn("seal://sign?", out, "the line is in what the chat shows")
        self.assertNotEqual(self.slash("pass", "soon")[0], 0)

    def test_status_says_where_the_lock_stands(self):
        self.assertIn("the lock is off", self.slash("status")[1])
        self.locked()
        self.assertIn("the lock is ON", self.slash("status")[1])


class WhatGetsThroughALockedDoor(SealTestCase):
    def test_the_five_safe_commands_typed_alone(self):
        self.locked()
        for typed in ("/seal:status", "/seal:on", "/seal:off", "/seal:drop", "/seal:pass", "/seal:pass 90", "  /seal:off  "):
            self.assertEqual(self.door(self.message(typed))[0], 0, typed)

    def test_nothing_else(self):
        self.locked()
        for typed in ("/seal:pair", "/seal:git", "/seal:off and delete the tests", "please /seal:off",
                      "/seal:off\nrm -rf ~", "/seal:pass 99999", "/seal:status; ls", "/seal:offf", "/seal off"):
            self.assertEqual(self.door(self.message(typed))[0], 2, typed)

    def test_a_tool_is_never_let_through_by_words(self):
        self.locked()
        event = dict(self.tool(), prompt="/seal:status")
        self.assertEqual(self.door(event)[0], 2)


class TurningItOff(SealTestCase):
    def test_off_needs_the_phones_yes_for_exactly_that(self):
        self.locked()
        status, out, _ = self.slash("off")
        self.assertEqual(status, 0)
        self.assertIn("needs a yes from your phone", out)
        self.assertTrue(self.lock_is_on(), "asking turns nothing off")
        purpose, words = read_request(self.copied())
        self.assertEqual(purpose, "seal-agent")
        self.assertIn(b'Allow once: "Turn the Seal lock off"', words)

        # Without the answer, asking again shows the same request.
        self.assertEqual(self.slash("off")[0], 0)
        self.assertEqual(read_request(self.copied())[1], words)
        self.assertTrue(self.lock_is_on())

        self.answer_waiting_request()
        status, out, _ = self.slash("off")
        self.assertEqual(status, 0, out)
        self.assertIn("the lock is off", out)
        self.assertFalse(self.lock_is_on())
        self.assertEqual(self.door(self.tool())[0], 0)

    def test_another_key_or_another_purpose_does_not_turn_it_off(self):
        self.locked()
        self.slash("off")
        stranger = Phone(self.folder, "stranger")
        _, words = read_request(self.copied())
        for signature in (stranger.sign(words, "seal-agent"), self.phone.sign(words, "seal-pass"), self.phone.sign(words, "git")):
            self.copy(signature)
            _, out, _ = self.slash("off")
            self.assertIn("not your phone's yes", out)
            self.assertTrue(self.lock_is_on())

    def test_a_yes_counts_once(self):
        self.locked()
        self.slash("off")
        self.answer_waiting_request()
        signature = self.copied()
        self.slash("off")
        self.assertFalse(self.lock_is_on())
        self.slash("on")
        self.slash("off")             # a new request
        self.copy(signature)          # the old yes again
        self.slash("off")
        self.assertTrue(self.lock_is_on())

    def test_a_pass_is_no_yes_to_turning_off(self):
        self.locked()
        self.door(self.message("hello"))            # asks for a pass
        self.answer_waiting_request()               # the phone signs the pass
        self.assertEqual(self.door(self.message("hi"))[0], 0)
        self.slash("off")
        self.assertTrue(self.lock_is_on(), "a good pass does not switch the lock off")

    def test_the_yes_pasted_into_a_message_turns_it_off_from_far_away(self):
        self.locked()
        self.slash("off")
        _, words = read_request(self.copied())
        signature = self.phone.sign(words, "seal-agent")
        self.copy("something else")                 # far from the Mac: nothing comes by the clipboard
        status, out, _ = self.door(self.message("here you go " + signature.replace("\n", " ")))
        self.assertEqual(status, 0)
        self.assertIn("The lock is off now", out)
        self.assertFalse(self.lock_is_on())

    def test_off_when_already_off(self):
        self.assertIn("already off", self.slash("off")[1])


class Pairing(SealTestCase):
    def test_pair_takes_the_public_key_from_the_clipboard(self):
        self.copy("Seal key for Seth\n" + self.phone.line + "\n")
        status, out, _ = self.slash("pair")
        self.assertEqual(status, 0, out)
        with open(os.path.join(self.state, "allowed_signers")) as handle:
            kept = handle.read()
        self.assertIn('namespaces="seal-agent,seal-pass"', kept)
        self.assertIn(self.phone.line.split()[1], kept)

    def test_pair_refuses_a_private_key_and_nothing(self):
        with open(self.phone.path) as handle:
            self.copy(handle.read())
        status, out, _ = self.slash("pair")
        self.assertEqual(status, 1)
        self.assertIn("private key", out)
        self.copy("hello")
        self.assertEqual(self.slash("pair")[0], 1)
        self.assertFalse(os.path.exists(os.path.join(self.state, "allowed_signers")))

    def test_no_new_key_while_the_lock_is_on(self):
        self.locked()
        thief = Phone(self.folder, "thief")
        self.copy(thief.line)
        status, out, _ = self.slash("pair")
        self.assertEqual(status, 1)
        self.assertIn("the lock is on", out)
        with open(os.path.join(self.state, "allowed_signers")) as handle:
            self.assertNotIn(thief.line.split()[1], handle.read())

    def test_a_new_key_ends_the_old_keys_passes(self):
        self.locked()
        self.door(self.message("hello"))
        self.answer_waiting_request()
        self.assertEqual(self.door(self.tool())[0], 0)
        # Off with the old phone, then a new phone.
        self.slash("off")
        self.answer_waiting_request()
        self.slash("off")
        self.phone = Phone(self.folder, "new-phone")
        self.paired()
        self.slash("on")
        self.assertEqual(self.door(self.tool())[0], 2, "the old phone's pass is no pass for the new key")


class GitSigning(SealTestCase):
    def setUp(self):
        super().setUp()
        self.repo = os.path.join(self.folder, "repo")
        os.makedirs(self.repo)
        for command in (["init", "-q", "-b", "main"], ["config", "user.email", "test@example.com"], ["config", "user.name", "Test"]):
            subprocess.run(["git", *command], cwd=self.repo, check=True)

    def git(self, *arguments, env=None):
        return subprocess.run(["git", *arguments], cwd=self.repo, capture_output=True, text=True, env=env or self.env, timeout=60)

    def test_git_needs_a_paired_phone(self):
        self.assertEqual(self.slash("git", cwd=self.repo)[0], 1)

    def test_a_commit_run_by_an_agent_is_signed_through_the_clipboard(self):
        self.paired()
        status, out, err = self.slash("git", cwd=self.repo)
        self.assertEqual(status, 0, out + err)
        program = self.git("config", "gpg.ssh.program").stdout.strip()
        self.assertEqual(program, os.path.join(self.state, "bin", "seal-git-sign"), "a copy that outlives plugin updates")

        def phone():
            # Wait for the request to show up on the clipboard, then answer it as the app would.
            for _ in range(200):
                if "seal://sign?v=1&ns=git" in self.copied():
                    self.answer_waiting_request()
                    return
                time.sleep(0.1)

        helper = threading.Thread(target=phone)
        helper.start()
        with open(os.path.join(self.repo, "a.txt"), "w") as handle:
            handle.write("a\n")
        self.git("add", "a.txt")
        done = self.git("commit", "-q", "-S", "-m", "signed by the phone")
        helper.join()
        self.assertEqual(done.returncode, 0, done.stderr)
        verdict = self.git("verify-commit", "HEAD")
        self.assertEqual(verdict.returncode, 0, verdict.stderr)
        self.assertIn("Good", verdict.stderr)

    def test_a_signature_from_another_key_is_not_given_to_git(self):
        self.paired()
        self.slash("git", cwd=self.repo)
        stranger = Phone(self.folder, "stranger")

        def wrong_phone():
            for _ in range(200):
                if "seal://sign?v=1&ns=git" in self.copied():
                    self.answer_waiting_request(by=stranger)
                    return
                time.sleep(0.1)

        helper = threading.Thread(target=wrong_phone)
        helper.start()
        with open(os.path.join(self.repo, "b.txt"), "w") as handle:
            handle.write("b\n")
        self.git("add", "b.txt")
        done = self.git("commit", "-q", "-S", "-m", "not signed", env=dict(self.env, SEAL_SIGN_WAIT="4"))
        helper.join()
        self.assertNotEqual(done.returncode, 0)
        self.assertNotEqual(self.git("rev-parse", "-q", "--verify", "HEAD").returncode, 0, "no commit was made")


class ThePluginFiles(unittest.TestCase):
    def test_both_doors_go_through_seal_hook_and_hold_when_it_fails(self):
        with open(os.path.join(ROOT, "hooks", "hooks.json")) as handle:
            hooks = json.load(handle)["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit", "PreToolUse"})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "*")
        for groups in hooks.values():
            one = groups[0]["hooks"][0]
            self.assertEqual(one["onFailure"], "block")
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/bin/seal-hook", one["command"])

    def test_every_command_is_the_persons_alone(self):
        folder = os.path.join(ROOT, "commands")
        names = sorted(name[:-3] for name in os.listdir(folder) if name.endswith(".md"))
        self.assertEqual(names, ["drop", "git", "off", "on", "pair", "pass", "status"])
        for name in names:
            with open(os.path.join(folder, name + ".md")) as handle:
                text = handle.read()
            self.assertIn("disable-model-invocation: true", text, name)
            self.assertIn('allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/bin/seal-gate":*)', text, name)
            self.assertIn(f'bin/seal-gate" slash {name}', text, name)


if __name__ == "__main__":
    unittest.main()
