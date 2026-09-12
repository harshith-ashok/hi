// Selective TTS (TODO.md Phase 5, "Output speech"): speaks only the
// backend's short spoken-summary (hi/ipc/spoken_summary.py already
// applied the hard skip rules — code/tables/long answers never reach
// this class at all).
//
// **Voice engine swapped per explicit request** ("fix the TTS... I want
// something that sounds actually like a human, maybe even use kokoro"):
// this used to speak via AVSpeechSynthesizer, the zero-dependency
// default this file's own comment once named as a deliberate starting
// point, not a final answer ("evaluate whether a nicer offline neural
// TTS is worth the extra setup" was left as a later call). It now fetches
// real Kokoro-synthesized audio from the backend (`POST /tts`,
// hi/tts_kokoro.py) and plays it via AVAudioPlayer instead of asking the
// OS to speak the text itself.

import AVFoundation
import Foundation

@MainActor
final class SpeechOutput: NSObject, ObservableObject {
    @Published private(set) var isSpeaking = false

    private let backend: BackendClient
    private var player: AVAudioPlayer?
    /// Guards against a late-arriving fetch (barge-in happened while the
    /// network request was still in flight) from starting playback after
    /// the user already asked for silence — bumped on every speak() call
    /// and stopSpeaking(), checked before actually playing.
    private var generation = 0

    init(backend: BackendClient) {
        self.backend = backend
        super.init()
    }

    /// Fetches and plays `text` as real speech — fire-and-forget from the
    /// caller's side (same as the AVSpeechSynthesizer version this
    /// replaces), but genuinely async internally since synthesis is now
    /// a network round trip rather than instant on-device work.
    func speak(_ text: String) {
        guard !text.isEmpty else { return }
        stopSpeaking()  // barge-in: a new utterance always interrupts a running one
        let thisGeneration = generation
        Task {
            guard let data = await backend.synthesizeSpeech(text: text) else { return }
            guard thisGeneration == generation else { return }  // superseded while fetching
            play(data)
        }
    }

    private func play(_ data: Data) {
        do {
            let newPlayer = try AVAudioPlayer(data: data)
            newPlayer.delegate = self
            player = newPlayer
            isSpeaking = newPlayer.play()
        } catch {
            player = nil
            isSpeaking = false
        }
    }

    /// Barge-in (TODO.md: "speaking stops immediately if the wake word or
    /// hover-listen is triggered again mid-speech") — called from
    /// AppDelegate the moment a new listening session begins.
    func stopSpeaking() {
        generation += 1  // invalidate any in-flight fetch from a previous speak()
        player?.stop()
        player = nil
        isSpeaking = false
    }
}

extension SpeechOutput: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            guard self.player === player else { return }  // a stale delegate callback from an already-superseded player
            self.isSpeaking = false
        }
    }
}
