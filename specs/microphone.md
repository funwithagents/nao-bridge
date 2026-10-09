---
code:
  - src/nao_bridge/microphone.py
  - src/nao_bridge/robot.py
  - src/nao_bridge/fake_robot.py
  - src/nao_bridge/bridge.py
  - src/nao_bridge/nao_websocket_server.py
tests:
  - tests/test_microphone.py
  - tests/test_bridge.py
  - tests/test_nao_websocket_server.py
---

# Mic feed — the one owner of the robot's microphone

**Status:** Implemented

## Purpose

The bridge's audio input: **one subscription** to the robot's microphone for the whole session, the last couple of seconds of capture kept in a ring, and **any number of subscribers**, each an `audio_input()` iterator. Each subscriber receives every chunk, in order, at its own pace: a speech recognizer, a wake-word detector, the WebSocket server's `Audio` stream, a level meter, a recorder.

A callback would give one consumer a stream it can't pace and can't rewind, and leave a second consumer nowhere to plug in; subscribers fix both.

### Why one feed

Naoqi **pushes** audio: once a service is registered and subscribed to `ALAudioDevice`, Naoqi calls its `processRemote(channels, samples_per_channel, timestamp, buffer)` on a Naoqi thread for every buffer ([robot.md](robot.md)). So:
- **The push is the publish.** The bridge runs no reader thread of its own. The robot seam's audio callback writes straight into the ring.
- **Naoqi already allows only one subscription per service name.** The feed is that subscription, and the subscribers fan out behind it.

## Core concepts / Decided

### The chunk

```python
@dataclass(frozen=True)
class MicChunk:
    seq: int      # 0, 1, 2, … per feed — the subscribers' cursor counts these
    ts: float     # time.monotonic() when the bridge received the buffer
    data: bytes   # int16 LE PCM, interleaved — the buffer Naoqi pushed, as is
    channels: int
    samples_per_channel: int
```

- **`seq`** increases by one per published chunk and keeps counting across sessions of the same bridge object. `published_count` is the next `seq`.
- **`ts`** is the arrival time on the monotonic clock. Naoqi's own `timestamp` argument is not used: it's on the robot's clock, and arrival time is what pre-roll needs.
- **`data`** is Naoqi's buffer copied once into `bytes`. It's shared by reference with every subscriber, and `bytes` is immutable, so no subscriber can alter what another reads.
- **No conversion:** Naoqi already delivers 16-bit little-endian PCM, which is the stream's contract. No numpy dependency.

### The feed

```
MicFeed()
  async .start(robot, channel) / async .stop()   # the bridge's to call (lifecycle below)
  .latest() -> MicChunk | None                   # newest chunk; None before the first / outside a session
  .published_count -> int                        # chunks published, ever, on this feed
  .sample_rate -> int                            # 16000
  .channels -> int                               # 1 with today's single-mic modes
  .subscribe(*, preroll_s)                       # the iterator behind audio_input()
```

- **Publishing.** `start()` subscribes to the robot's audio (`robot.subscribe_audio(self._publish)`). `_publish(channels, samples_per_channel, buffer)` runs on Naoqi's thread. Under the feed's lock it stamps the chunk (`seq`, `ts`), writes it into the ring and advances `head`. Outside the lock it wakes the waiting subscribers. The lock is held for the write only.
- **The ring.** The feed keeps the last `MIC_RING_CHUNKS = 200` chunks in a fixed array: chunk `seq` lives in slot `seq % MIC_RING_CHUNKS`. Its span in seconds is 200 chunk durations — about 17 s with the fake's 85 ms chunks — so it is sized in chunks, not seconds; open question 1 covers Naoqi's real chunk size.
- **Bound per session, alive per bridge.** `bridge.mic` exists from construction, with `latest()` returning `None`. `start()` / `stop()` are the bridge's to call: `NaoBridge.start()` starts the feed when `streams.audio.enabled` ([config.md](config.md)), and `NaoBridge.stop()` stops it before closing the robot. Stopping unsubscribes from the robot, ends every subscriber, and resets `latest()` to `None`.

### Subscribers — `audio_input()`

`bridge.audio_input(preroll_s=0.0)` returns a new subscriber: an async iterator over the ring yielding `bytes` (int16 LE), holding one integer, its **cursor** (the `seq` of the next chunk it yields). Every call is an independent subscriber, and any number can run at once. Each step compares the cursor with the feed's `head`:

| Cursor | Meaning | The step |
|---|---|---|
| `cursor == head` | caught up | waits until the next chunk is published |
| `head - MIC_RING_CHUNKS <= cursor < head` | behind, its chunk still in the ring | reads slot `cursor % MIC_RING_CHUNKS`, advances, yields `chunk.data` |
| `cursor < head - MIC_RING_CHUNKS` | lapped | logs one gap `WARNING` (chunks and milliseconds lost), moves the cursor to the oldest chunk in the ring, reads on |

- **A slow subscriber costs only itself.** Neither Naoqi's thread nor any other subscriber ever waits on it.
- **Where it starts:** by default at `head`. `preroll_s > 0` starts it at the oldest chunk whose `ts >= now - preroll_s`, never before the session's first chunk. A negative `preroll_s` raises `ValueError` at the call.
- **Checks at the call:** a bridge whose audio stream is disabled in the config raises `BridgeError`, and one that isn't running raises `NotRunningError` (a `BridgeError`), where `audio_input()` is called, not at the first `async for`.
- **End of session:** a subscriber ends on its own when the session stops (`stop()` wakes it and its iterator returns). It never carries over into a later session.
- **Cancellation:** `break`, cancelling the consuming task, or `aclose()` ends that subscriber only, unregistering it in a `finally`.
- **Waking across threads:** each waiting subscriber registers an `asyncio.Event` together with its loop. The publisher sets them through `loop.call_soon_threadsafe`, and a subscriber clears its event before reading `head`.
- **No `mono=` parameter.** With one microphone selected (`streams.audio.channel`) the capture is already mono. A multichannel mode would add `mono=` with a downmix (open question 2).

### `latest()`, for samplers

`bridge.mic.latest()` returns the newest chunk, read instantly from any thread. It's for consumers that sample rather than stream: a level meter, or an agent tool asking whether anyone is speaking. It takes nothing from any subscriber.

### Consumers in this repo

- **WebSocket server:** when the audio stream is enabled, a task per client session drains one `audio_input()` and sends each chunk as an `Audio` message: `{rate, channels, nbSamplesPerChannel, data: base64}`, the same wire format as today. The base64 encoding moves from the bridge to the server, where the JSON transport needs it.
- **MCP server:** no consumer. The stream is simply not enabled in its config.

### `fake` backend support

`FakeNaoRobot` ([robot.md](robot.md)) pushes like Naoqi. While audio is subscribed, a thread pushes a silent chunk every `audio_chunk_s` (default 0.085 s, 1360 samples at 16 kHz). `emit_audio(...)` stays available to push chosen content.

`tests/` check on the fake:
- two subscribers both receive every `seq`, in order;
- a subscriber stalled past a shortened ring reports one gap and resumes at the oldest chunk, while a fast one beside it loses nothing;
- `preroll_s` yields chunks published before the call;
- a cancelled subscriber leaves the others streaming;
- every subscriber ends when the session stops;
- `latest()` is `None` before `start()` and after `stop()`.

## Relationship to the other specs

- **[config.md](config.md):** `streams.audio.enabled` and `streams.audio.channel` decide whether, and from which microphone, the feed subscribes.
- **[bridge.md](bridge.md):** `bridge.mic`, `audio_input(preroll_s)`, `MicChunk` exported.
- **[robot.md](robot.md):** `subscribe_audio(callback, channel)`, whose only caller is the feed; the fake's paced push.
- **[nao-websocket-server.md](nao-websocket-server.md):** the `Audio` message is produced by an `audio_input()` subscriber; its wire format is unchanged.

## Open questions

1. **Naoqi's chunk size at 16 kHz single-channel.** It has to be measured on the robot (`samples_per_channel` per `processRemote`); the fake's 1360 is a placeholder. The ring counts chunks, so this changes the ring's span in seconds, not its rules. If chunks are large, a ring sized in seconds (`ceil(2 s / chunk)`) may read better.
2. **Multichannel capture.** Naoqi's all-microphones mode is 48 kHz, 4 interleaved channels. It would bring in a `mono=` option (downmix, the default) and a raw mode for direction-of-arrival. Deferred until a consumer needs it.
3. **Strict continuity:** a way to surface a gap in the stream itself rather than only in the log, for a recorder. Deferred.
