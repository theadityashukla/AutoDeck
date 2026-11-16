"""Meeting transcription: local, offline speech-to-text for recorded meetings.

Stage A turns a recording into a timestamped (optionally speaker-labelled) transcript. It
is a separate package because its heavy dependencies (sherpa-onnx, ffmpeg) are an optional
extra, and because recordings are client-confidential: nothing here touches the network
except the one-off model download, and nothing logs transcript text.
"""
