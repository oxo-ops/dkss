"""Dashboard score interpretation, independent of HTTP and database access."""


class DashboardScoring:
    @staticmethod
    def score_value(value):
        text = str(value if value is not None else "").strip()
        symbol_scores = {
            "○": 2.0,
            "〇": 2.0,
            "✓": 2.0,
            "✔": 2.0,
            "☑": 2.0,
            "△": 1.0,
            "▲": 1.0,
            "×": 0.0,
            "✕": 0.0,
            "✖": 0.0,
            "✗": 0.0,
            "✘": 0.0,
            "X": 0.0,
            "x": 0.0,
        }
        if text in symbol_scores:
            return symbol_scores[text]
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def values(self, check_items, answers):
        """Yield each answered numeric item once, using its own choices as the maximum."""
        for item, answer in zip(check_items, answers):
            if item.get("input_type") != "select":
                continue
            choices = [self.score_value(choice) for choice in item.get("choices", [])]
            choices = [value for value in choices if value is not None]
            if not choices:
                continue
            score = self.score_value(answer.get("value"))
            if score is not None:
                yield item, score, max(choices)
