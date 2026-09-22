"""Project-scoped Manim launcher with synchronous frame submission."""


def configure_encoder(stream):
    """Limit codec buffering without changing resolution, frame rate or CRF."""
    context = stream.codec_context
    context.thread_count = 1
    if context.name == "libx264":
        options = dict(context.options)
        options.update({
            "tune": "zerolatency",
            "rc-lookahead": "0",
            "sync-lookahead": "0",
            "bf": "0",
            "refs": "1",
            "threads": "1",
        })
        context.options = options


class ImmediateFrames:
    def __init__(self, queue, encode):
        self.queue = queue
        self.encode = encode

    def put(self, message):
        count, frame = message
        if frame is None:
            self.queue.put(message)
        else:
            self.encode(frame, count)

    def get(self, *args, **kwargs):
        return self.queue.get(*args, **kwargs)


def install():
    from manim.scene.scene_file_writer import SceneFileWriter
    original = SceneFileWriter.open_partial_movie_stream
    def open_stream(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if getattr(self, "video_stream", None) is not None:
            configure_encoder(self.video_stream)
        # The worker waits on its empty queue; only the shutdown sentinel is
        # forwarded. Actual encoding happens on the rendering thread.
        if hasattr(self, "queue") and hasattr(self, "encode_and_write_frame"):
            self.queue = ImmediateFrames(self.queue, self.encode_and_write_frame)
        return result
    SceneFileWriter.open_partial_movie_stream = open_stream


if __name__ == "__main__":
    install()
    from manim.__main__ import main
    main()
