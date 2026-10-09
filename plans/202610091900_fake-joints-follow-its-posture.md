# Fake joints follow its posture

**Status:** Done

Implements the edit to `specs/robot.md` ("`FakeNaoRobot`", Joints). The fake used to report only `HeadYaw` / `HeadPitch` at fixed angles, so a client that animates a whole Nao (the Unity viewer) got no update for 24 of its joints, and nothing changed when the robot stood up or sat down. Now the fake reports Naoqi's 26 `Body` joints at the angles of the posture it's in (`Crouch` at rest, `Stand`, `Sit`), and tracks that posture through `rest()` and `go_to_posture`, as a Nao would.

The angles were measured on a simulated Nao (nao-sim, Naoqi's `ALRobotPosture` then `ALMotion.getAngles("Body", False)` per posture). Not in scope: moving through intermediate poses during a posture move, and other Naoqi postures (`StandInit`, `LyingBack`, …), which leave the pose unchanged.

## Scope

- `src/nao_bridge/fake_robot.py`: `_POSTURE_TABLE`, `JOINT_NAMES`, `POSTURE_ANGLES`, `REST_POSTURE`; `posture` replaces `joint_names` / `joint_angles`; `rest()` / `go_to_posture` move it; `_wait_unless_ended` says whether the wait was ended early.
- `tests/test_fake_robot.py`: posture tracking, and a failed / stopped / unknown move keeps the pose.
- `tests/test_bridge.py`: the joints stream follows `wake_up` / `stand_up` / `sit_down` / `rest`; the existing joints test expects the crouched pose.
- `tests/test_nao_websocket_server.py`: the first `Joints` message is the crouched pose.
- `specs/robot.md`, `specs/_index.md`, `AGENTS.md` (project map), `README.md`.

## Steps

1. The posture table and the posture state in the fake.
2. The tests above.
3. The angles, measured on nao-sim.
4. Spec, index, map and README.

## Verification

Done 2026-10-09: ruff and pyright are clean, and all tests pass. The posture angles were measured against nao-sim (Naoqi at `127.0.0.1:9559`).
