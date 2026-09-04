// Selective TTS (TODO.md Phase 5, "Output speech"): speaks only the
// backend's short spoken-summary (hi/ipc/spoken_summary.py already
// applied the hard skip rules — code/tables/long answers never reach
// this class at all), via AVSpeechSynthesizer, the zero-dependency
// default TODO.md itself names ("evaluate whether a nicer offline neural
// TTS is worth the extra setup" was left as a later call, not made here).

import AVFoundation
import Foundation

@MainActor
final class SpeechOutput: NSObject, ObservableObject {
    @Published private(set) var isSpeaking = false

    private let synthesizer = AVSpeechSynthesizer()

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ text: String) {
        guard !text.isEmpty else { return }
        stopSpeaking()  // barge-in: a new utterance always interrupts a running one
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        synthesizer.speak(utterance)
    }

    /// Barge-in (TODO.md: "speaking stops immediately if the wake word or
    /// hover-listen is triggered again mid-speech") — called from
    /// AppDelegate the moment a new listening session begins.
    func stopSpeaking() {
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
    }
}

extension SpeechOutput: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didStart utterance: AVSpeechUtterance) {
        Task { @MainActor in self.isSpeaking = true }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.isSpeaking = false }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.isSpeaking = false }
    }
}
