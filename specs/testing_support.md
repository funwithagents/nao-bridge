---
code:
  - src/naoqi_bridge/testing/__init__.py
  - src/naoqi_bridge/testing/capabilities.py
  - src/naoqi_bridge/testing/target.py
  - src/naoqi_bridge/testing/plugin.py
  - pyproject.toml
tests:
  - tests/test_testing.py
---

# Testing support (shipped live-tier harness)

**Status:** Implemented

## Purpose

`naoqi_bridge.testing` is the bridge's **shipped live-tier harness**: what a project built on the bridge imports to run its own live tests against a Naoqi, a naoqi-sim or a real Nao, without re-deriving how to start a sim for a test session, how to tell what the target can do, and how to keep a test that moves the robot from running where it shouldn't.

Its core idea is **capabilities**: named things the target offers (`dances`, `apps`, `camera`, `audio_inject`, `touch_sensors`, …) or the person running the tests vouches for (`room_to_move`, `person_present`). The harness probes them once per run. A test declares what it needs with a `@pytest.mark.requires(...)` marker, and runs wherever its needs are met and skips elsewhere. A test therefore never asks *which* target it is on (`sim` or `real`, 2.1 or 2.8), only *what* the target can do. Adding a target (a NAOqi version, a robot model) means probing it, not editing tests.

This spec governs code that ships in `src/`. [testing.md](testing.md) is the bridge's own testing practice: which of its live tests need what, and how its tiers run. The bridge's `tests-e2e/` uses this harness, so the shipped harness is the code the bridge's own live tier runs, not a second copy.

## Decided

### Shipped as `naoqi_bridge.testing`, behind a `[test]` extra

- **The `[test]` extra** adds `pytest` (floor `>=9.1.1`, the dev group's), the harness's only dependency of its own. A consumer's live tier installs `naoqi-bridge[sim,test]` for the `sim` target, or `naoqi-bridge[test]` for a robot. The harness needs `qi` to reach a target, so the live tier runs where `qi` does ([project.md](project.md)).
- **`import naoqi_bridge` never imports `naoqi_bridge.testing`**: pytest stays out of the runtime dependencies, and the package front door re-exports nothing from it.
- **Package layout:**

  | Module | Holds |
  |---|---|
  | `testing/__init__.py` | Re-exports `LiveTarget`, `requires_caps`, `live_config`, `live_bridge_dict`, `live_session` |
  | `testing/capabilities.py` | The vocabulary (probed and declared names), the probes, the profiles, the parsing of `NAOQI_E2E_DECLARED_CAPS` / `NAOQI_E2E_PROFILE` / `NAOQI_E2E_REQUIRED_CAPS`, the check behind the marker and `requires_caps` |
  | `testing/target.py` | The environment (target, version, address), the session's sim, `LiveTarget`, the config helpers and `live_session` |
  | `testing/plugin.py` | The pytest plugin: the `live_target` fixture, the `requires` marker and its gate, the terminal summary section |

- **Opt-in as a plugin, no auto-registration.** There is no `pytest11` entry point, so depending on the bridge never adds fixtures to an unrelated test run, nor starts a sim in one. A consumer names it from its rootdir conftest: `pytest_plugins = ["naoqi_bridge.testing.plugin"]`. The bridge's own `tests-e2e/conftest.py` is not a rootdir conftest, so it imports the plugin's fixtures and hooks by name.

### The environment

One target per run, chosen by the environment. Every variable is read once, at `pytest_configure`. An unknown target, version or capability name fails the run at once (`pytest.UsageError`) and names the accepted words.

| Variable | Values | Meaning |
|---|---|---|
| `NAOQI_E2E_TARGET` | `sim` (when unset), `real` | The backend the tests' bridges use. Set by name, a target that can't run fails the run instead of skipping it (below) |
| `NAOQI_E2E_SIM_VERSION` | `2.1` (when unset), `2.8` | `sim`: the NAOqi version of the session's sim |
| `NAOQI_E2E_SIM_VIEWER` | a flag (`1`, `true`, `yes`) | `sim`: the sim's window instead of a headless sim, to watch the run |
| `NAOQI_E2E_IP`, `NAOQI_E2E_PORT` | an address, a port (9559 when unset) | `real`: the robot |
| `NAOQI_E2E_ALLOW_MOTION` | a flag (`1`, `true`, `yes`) | `real`: the floor is clear and someone is watching. Declares `room_to_move` (below) |
| `NAOQI_E2E_INTERACTIVE` | a flag | Someone is at the robot to act on prompts. Declares `person_present` |
| `NAOQI_E2E_VIEWER` | a flag | Either target: the host has a display that the run may open windows on. Declares `display` |
| `NAOQI_E2E_DECLARED_CAPS` | comma-separated declared capabilities | The generic form of the three flags, for a declared capability that has no flag of its own (below) |
| `NAOQI_E2E_PROFILE` | a profile name; `sim` on the `sim` target when unset, none on `real` | The capabilities the target is expected to offer: a missing one fails the run (below, "Profiles") |
| `NAOQI_E2E_REQUIRED_CAPS` | comma-separated capabilities, probed or declared | Required on top of the profile: a missing one fails the run instead of skipping its tests (below) |

### Capabilities

A capability is a name in a closed vocabulary. It comes from one of two sources, and a name belongs to exactly one of them:

- **Probed**: a fact about the target, read from it at session start. Nobody can declare it.
- **Declared**: a fact about the room or the host that no probe can see, such as whether the robot has space to move or whether someone stands next to it. It comes from `NAOQI_E2E_DECLARED_CAPS`, or, for each of today's three, from the flag that stands for it (`NAOQI_E2E_ALLOW_MOTION`, `NAOQI_E2E_INTERACTIVE`, `NAOQI_E2E_VIEWER`). The flags keep the commands people already run; `NAOQI_E2E_DECLARED_CAPS` is there for a declared capability added later, which then gets a flag only if it is common enough to deserve one. Declaring a probed name is a `UsageError`.

**A name joins the vocabulary when a test needs it, the bridge's or a consumer's, and a profile pins it.** A probe that neither a test nor a profile uses is code nobody checks. `camera` gates the bridge's live camera test ([camera.md](camera.md)), consumers can gate on it, and the `sim` profile pins it, so its probe is checked against a live sim on every CI run. The candidates waiting for a need are listed under Open questions.

**Probed:**

| Capability | Meaning | Probe | sim 2.1 | sim 2.8 | Nao (stock) |
|---|---|---|---|---|---|
| `sim` | The target is naoqi-sim | The `NaoqiSim` service exists ([naoqi-sim's status service](https://github.com/funwithagents/naoqi-sim/blob/main/specs/container/status-service.md)) | ✅ | ✅ | ❌ |
| `audio_in` | Naoqi pushes microphone audio | On naoqi-sim, `NaoqiSim/Audio/Source` in ALMemory isn't `none`; elsewhere, the `ALAudioDevice` service exists | ✅ (`fake` source) | ✅ | ✅ |
| `audio_inject` | A test can play a sound into the microphone | The session owns the sim (`LiveTarget.sim` isn't `None`) and its audio input is `fake` | ✅ | ✅ | ❌ |
| `touch_sensors` | Head touch sensors a person can press | Not naoqi-sim: its sensors aren't physical. Pressing them programmatically will be a capability of its own (Open questions) | ❌ | ❌ | ✅ |
| `dances` | The catalog holds at least one dance | `get_dance_behaviors()` on the probe's bridge isn't empty | ❌ | ❌ | the robot's packages |
| `body_actions` | The catalog holds at least one body action | `get_body_action_behaviors()` on the probe's bridge isn't empty | ❌ | ❌ | ✅ (`dialog_move_arms`) |
| `apps` | The catalog holds at least one app | `get_app_behaviors()` on the probe's bridge isn't empty | ❌ | ❌ | the robot's packages |
| `camera` | Naoqi serves camera images | On naoqi-sim, `NaoqiSim/Camera/Source` in ALMemory isn't `none`; elsewhere, the `ALVideoDevice` service exists | ✅ (`render` source) | ✅ | ✅ |

The sim columns are the headless sim the harness starts ([testing.md](testing.md)). A sim someone else started holds what its own config gives it.

**Declared:**

| Capability | Meaning | Who holds it |
|---|---|---|
| `room_to_move` | The robot may move its limbs: the floor is clear and someone is watching | Always held on the `sim` target, where the harness adds it. On `real`, when `NAOQI_E2E_ALLOW_MOTION` is set, or declared |
| `person_present` | Someone at the robot acts on prompts (touches the head) | When `NAOQI_E2E_INTERACTIVE` is set, or declared |
| `display` | The host has a display that the run may open windows on | When `NAOQI_E2E_VIEWER` is set, or declared |

### Facts, not gates

`LiveTarget.naoqi_version` is the target's full NAOqi version: `NaoqiSim/NaoqiVersion` on naoqi-sim, `ALSystem.systemVersion()` on a robot, `None` when it can't be read. It is reported in the summary and available to a test that checks the version itself, but **there is no version marker**. When a behavior differs between versions, the cause is something a version only stands in for: the 2.8 desktop suite has no inertial sensor, but a 2.8 robot does. A test that depends on such a difference gates on a capability that names the cause.

### Profiles

A profile is a named set of capabilities a kind of target is expected to offer, defined in the harness (`testing/capabilities.py`). It turns "this target should have X" from knowledge in someone's head into a check: the run **fails** when the target lacks a capability its profile names, as with `NAOQI_E2E_REQUIRED_CAPS`, whose names add to the profile's.

| Profile | Expected capabilities | For |
|---|---|---|
| `sim` | `sim`, `audio_in`, `audio_inject`, `camera`, `room_to_move` | The sim the harness starts, on both versions, headless or with its window. **The default on the `sim` target**: the harness picks that sim's config, so a capability missing there is a fault, locally as in CI |
| `nao` | `audio_in`, `camera`, `touch_sensors`, `body_actions` | A stock Nao: `NAOQI_E2E_PROFILE=nao` on the `real` target |
| `none` | nothing | Turns the default off, e.g. to run against a sim with a config of its own |

- **A profile lists probed capabilities and, for `sim`, the one the target itself grants**: never a declared one a person has to vouch for. `room_to_move` on a robot, `person_present` and `display` stay explicit choices of whoever runs the tests, so no profile makes a robot move.
- **A profile is the floor, not the whole set.** A target that offers more (a robot with dances) runs more tests; the summary shows the full set.
- **A version difference gets its own profile only when the capabilities differ**: today 2.1 and 2.8 sims share `sim`. The first capability that splits them (`inertial`, Open questions) would make `sim-2.1` and `sim-2.8`.
- **Consumers** name a profile or list their own needs in `NAOQI_E2E_REQUIRED_CAPS`; a consumer-defined profile is an open question.

### The probe

- **Once per run**, in `live_target`'s setup: after the session's sim is acquired, or straight away on `real`. The capabilities belong to the target, not to a test, so every test reuses them.
- **Two connections, both closed before the first test.** The harness's own `qi.Session` to the target's URL handles the service list and ALMemory reads. One bridge on `live_config()`, with no streams, handles the catalog, so `dances`, `body_actions` and `apps` use the classifier the tests' bridges use.
- **Single reads, no waits.** naoqi-sim reports its device sources itself, so no probe waits for a chunk or a frame.
- **A probe that raises means the capability is absent**, logged as a warning that names the probe. A target that can't be connected to at all is not a missing capability: that is the "can't run" case below.

### `LiveTarget`

```python
@dataclass(frozen=True)
class LiveTarget:
    kind: Literal["sim", "real"]
    naoqi_version: str | None
    probed: frozenset[str]
    declared: frozenset[str]    # from the flags and NAOQI_E2E_DECLARED_CAPS, plus room_to_move on sim
    sim: NaoqiSim | None        # the session's sim, for naoqi-sim's own API (fake_audio); None on real

    @property
    def caps(self) -> frozenset[str]: ...   # probed | declared
```

### The `live_target` fixture

A session-scoped, autouse fixture in the plugin. It brings the target up, probes it, checks the expected capabilities (the profile's and the required ones), and yields the `LiveTarget`. At session end it releases what it started.

- **On `sim`** it owns the session's sim. It calls `acquire_sim` with `spawn: "always"` on an event loop in a thread of its own, which runs both the start and the stop, and releases the lease at session end. It uses `always` because naoqi-sim's own API (`NaoqiSim.fake_audio`) lives only in the process that started the sim, and because a test session must never drive a sim someone else runs. The sim's config is headless with the render camera, the placeholder robot model, a silent loudspeaker and the `fake` audio input, or the window with `NAOQI_E2E_SIM_VIEWER=1`. The harness never builds images.
- **On `real`** it connects to `NAOQI_E2E_IP` / `NAOQI_E2E_PORT`.
- **When the target can't run**, it fails or skips depending on whether the target was asked for. The cases are: no `qi`, no `[sim]` extra, no Docker, images missing or outdated, a naoqi-sim already running, a taken port, `real` without `NAOQI_E2E_IP`, or a robot that doesn't answer.
  - `NAOQI_E2E_TARGET` unset: every test skips, with the reason.
  - `NAOQI_E2E_TARGET` set: every test fails with the reason.
- **Expected capabilities.** When the profile or `NAOQI_E2E_REQUIRED_CAPS` names one that `caps` lacks, the fixture fails. Every test then errors at setup, with a message naming what's missing and listing the capability set. CI uses this to tell a sim whose audio input didn't come up from a target that has none.

### The `requires` marker

```python
@pytest.mark.requires("dances", "room_to_move")
def test_stop_dance_ends_a_dance_and_its_verb_returns(): ...
```

- It goes on a test, a class, or a module's `pytestmark`. Several marks add up.
- **It is checked at the test's setup, before the test body runs**, by an autouse fixture of the plugin. So no bridge starts and no robot wakes for a test that skips.
- **The skip says which kind of capability is missing:**
  - probed: `the target lacks dances`;
  - declared: `needs room_to_move: set NAOQI_E2E_ALLOW_MOTION=1 once <its meaning>`, naming the capability's flag, or `NAOQI_E2E_DECLARED_CAPS` for one without a flag.
- **An unknown name in a marker is a `UsageError` at collection**, so a typo fails the run instead of skipping a test forever. The plugin registers the marker in `pytest_configure`, so it passes `--strict-markers`.
- **`requires_caps(target, *caps)`** runs the same check from inside a test, for a need that is only known at run time.

### Helpers

- `live_config(streams=None)` is the target's `NaoqiBridgeConfig` with the given streams: the session's sim borrowed (`backend: "sim"`, `spawn: "never"`, the run's version), or the robot. `live_bridge_dict(streams=None)` is the same as JSON, for a server run in a subprocess.
- `live_session(config, *, motion=False)` is the context manager a live test opens its bridge with. It starts the bridge and, on exit, leaves the robot as it found it, eyes white, even when the test failed. With `motion=True` the test is one that moves the robot: the motors are woken (`wake_up()`) once the bridge has started, and the robot is put to `rest` on exit. Whether such a test may run is the marker's decision (`room_to_move`). **`motion=True` without `room_to_move` fails the test**: a test that moves the robot without the marker is a test bug, not a skip.
- What is the bridge's own stays in its `tests-e2e/support.py`: the cancel measurements and their summary, the catalog pickers, and reads of Naoqi's own state through `bridge.robot`.

### The terminal summary

The plugin adds a `live target` section to the run's summary: the kind, the NAOqi version, the probed and the declared capabilities, the profile and the expected ones. With `-rs`, each skip reason names the capability it lacked.

### Testing

- **Fast tier** (`tests/test_testing.py`):
  - The probes against a stub `qi` session (a service list and ALMemory values) shaped as a 2.1 sim, a 2.8 sim and a robot, with one that raises.
  - The environment rules: unknown names (capabilities and profiles), declaring a probed name, `room_to_move` on `sim`, each flag declaring its capability, the default profile per target.
  - Through `pytester`, with `live_target` overridden by a fixed `LiveTarget`: the marker's skips and their messages, a typo as a `UsageError` at collection, a capability missing from the profile or the required ones as a setup error, and `live_session(motion=True)` failing without `room_to_move`.
- **Live tier**: the bridge's own `tests-e2e/`, which runs on the harness, its sim held to the `sim` profile in CI ([ci.md](ci.md)).

## Open questions

1. **Capabilities waiting for a test.** Each joins the vocabulary with the first test that gates on it:
   - `touch_inject`: naoqi-sim's touch input, once it exists, probed as `NaoqiSim/Touch/Source`. The touch test can then press the head itself on a sim.
   - `inertial`: the inertial sensor's ALMemory keys read. The same probe could then replace the bridge's "Sit through Crouch on a 2.8 sim" rule, which would be a [robot.md](robot.md) change.
   - The robot model (Nao v5, v6, Pepper), as a fact.
2. **Consumer-defined profiles.** A consumer whose robots share a setup may want to name it (a pytest hook or an ini option adding profiles). Deferred until one asks for it.
3. **A `fake` target** would let a consumer's live tests run as a smoke test with no Naoqi. The probes read Naoqi over `qi`, so the fake would need capabilities of its own. Deferred until a consumer asks for it.
