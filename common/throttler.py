import asyncio


class Throttler:
    def __init__(self, interval=2):
        """
        Returns true (means throttled) if called more than one per {interval} seconds.
        """
        self.interval = interval
        self.busy = False

    def __call__(self):
        if not self.busy:
            self.busy = True
            asyncio.get_event_loop().call_later(self.interval, self.done)
            return False

        return True

    def done(self):
        self.busy = False
