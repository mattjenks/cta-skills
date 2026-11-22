import subprocess

import health_check as hc


class Fake:
    def __init__(self, docker_ok_after=0, smoke_rc=0):
        self.docker_calls = 0
        self.docker_ok_after = docker_ok_after
        self.smoke_rc = smoke_rc
        self.notes = []
        self.now = 0.0

    def run(self, cmd, **kw):
        if cmd[0] == "docker":
            self.docker_calls += 1
            rc = 0 if self.docker_calls > self.docker_ok_after else 1
            return subprocess.CompletedProcess(cmd, rc, "", "")
        if cmd[0] == "osascript":
            self.notes.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, self.smoke_rc, "", "smoke boom")

    def sleep(self, s):
        self.now += s

    def clock(self):
        return self.now


def go(f):
    return hc.main(run=f.run, sleep=f.sleep, clock=f.clock)


def test_success_no_notify(capsys):
    f = Fake(docker_ok_after=2)
    assert go(f) == 0
    assert f.notes == []
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_docker_never_ready_notifies(capsys):
    f = Fake(docker_ok_after=10**6)
    assert go(f) == 1
    assert len(f.notes) == 1
    assert "CTA telemetry" in " ".join(f.notes[0])
    assert f.now >= 300


def test_smoke_fails_notifies():
    f = Fake(smoke_rc=1)
    assert go(f) == 1
    assert len(f.notes) == 1
    assert "CTA telemetry" in " ".join(f.notes[0])
