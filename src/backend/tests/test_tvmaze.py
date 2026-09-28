from src.features.metadata.tv.tvmaze import TVMazeClient


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.payload)


def test_tvmaze_search_prefers_medium_poster_for_fast_form_preview():
    session = _FakeSession(
        [
            {
                "show": {
                    "id": 123,
                    "name": "Example Show",
                    "image": {
                        "medium": "https://static.tvmaze.com/uploads/images/medium_portrait/1/2.jpg",
                        "original": "https://static.tvmaze.com/uploads/images/original_untouched/1/2.jpg",
                    },
                }
            }
        ]
    )

    result = TVMazeClient(session=session).search("Example Show")[0]

    assert result["poster_url"] == session.payload[0]["show"]["image"]["medium"]
    assert result["poster_url"] != session.payload[0]["show"]["image"]["original"]
