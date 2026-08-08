# Abstraction over "where am I right now", so app.py never needs to know
# whether the position came from a config file or real hardware.


class LocationProvider:
    """Base class. Concrete providers return (latitude, longitude) in
    decimal degrees from .get()."""

    def get(self):
        raise NotImplementedError


class HardcodedLocation(LocationProvider):
    """Always returns the same fixed point, e.g. read once from .env."""

    def __init__(self, lat, lon):
        self._lat = lat
        self._lon = lon

    def get(self):
        return (self._lat, self._lon)


class GPSLocation(LocationProvider):
    """Placeholder for a future GPS-backed location provider.

    No GPS sensor is wired up on the badge yet. When one exists, replace the
    body of get() with a read from that sensor's driver -- app.py only ever
    calls .get(), so nothing else needs to change.

    An optional fallback provider (e.g. HardcodedLocation) can be supplied so
    the app keeps working -- with a stale/approximate position -- if the GPS
    hasn't got a fix yet.
    """

    def __init__(self, fallback=None):
        self._fallback = fallback

    def get(self):
        if self._fallback is not None:
            return self._fallback.get()
        raise NotImplementedError("No GPS sensor wired up yet")
