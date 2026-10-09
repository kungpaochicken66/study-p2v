class RenderError(Exception):
    """Only static codes leave the renderer; command output and input text stay private."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Conflict(RenderError):
    pass


class QueueFull(RenderError):
    pass
