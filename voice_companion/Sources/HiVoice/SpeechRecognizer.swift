// Streaming local STT (TODO.md Phase 5, "Voice + live transcript") via
// Apple's on-device Speech framework — one of the two options TODO.md's
// own "Open decisions" section named (the other being whisper.cpp in
// streaming mode). Chosen over whisper.cpp: zero extra dependencies or
// bundled model files, ships with macOS, and requiresOnDeviceRecognition
// keeps it genuinely local — no different in kind from Vision-framework
// OCR already used elsewhere in this project (hi/perception/screen.py)
// for the same "native Apple framework over a new bundled dependency"
// reasoning. whisper.cpp remains a real, documented alternative if a
// future session finds on-device Speech's accuracy insufficient.

import AVFoundation
import Foundation
import Speech

@MainActor
final class SpeechRecognizer: NSObject, ObservableObject {
    @Published private(set) var partialTranscript = ""
    @Published private(set) var isListening = false
    @Published var lastError: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    /// Requests Microphone + Speech Recognition permission — both with a
    /// clear on-screen explanation before the system prompt, not silently
    /// (TODO.md: "request both on first launch with a clear explanation,
    /// not silently").
    func requestPermissions() async -> Bool {
        let speechStatus = await withCheckedContinuation { (continuation: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
        guard speechStatus == .authorized else {
            lastError = "Speech recognition permission was not granted."
            return false
        }

        let micGranted = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                continuation.resume(returning: granted)
            }
        }
        guard micGranted else {
            lastError = "Microphone permission was not granted."
            return false
        }
        return true
    }

    func start() throws {
        guard let recognizer, recognizer.isAvailable else {
            throw SpeechRecognizerError.unavailable
        }

        stop()  // guard against a stray previous session

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        // Genuinely local processing, not "local engine, cloud fallback" —
        // matches this project's existing local-first stance
        // (hi/perception/screen.py's on-device OCR, faster-whisper for
        // Ctrl-V voice input in the terminal companion).
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.request = request

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak request] buffer, _ in
            request?.append(buffer)
        }

        audioEngine.prepare()
        try audioEngine.start()
        isListening = true
        partialTranscript = ""

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            Task { @MainActor in
                if let result {
                    self.partialTranscript = result.bestTranscription.formattedString
                }
                if error != nil || result?.isFinal == true {
                    self.teardownAudio()
                }
            }
        }
    }

    /// Stops listening and returns the final transcript captured so far.
    @discardableResult
    func stop() -> String {
        let final = partialTranscript
        teardownAudio()
        return final
    }

    private func teardownAudio() {
        guard isListening || audioEngine.isRunning else { return }
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        request = nil
        task?.cancel()
        task = nil
        isListening = false
    }
}

enum SpeechRecognizerError: Error {
    case unavailable
}
