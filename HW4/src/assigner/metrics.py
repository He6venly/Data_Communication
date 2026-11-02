"""라운드별 측정값을 구간과 전체 통계로 모은다."""

from .barrier import RoundMeasurement


class Metrics:
    def __init__(self, n: int):
        self.n = n
        self.measurements: list[RoundMeasurement] = []

    def add(self, measurement: RoundMeasurement) -> dict | None:
        if measurement.round != len(self.measurements):
            raise ValueError("측정한 라운드 순서가 잘못됐습니다")
        if not 0 <= measurement.slowest < self.n:
            raise ValueError("최지연 작업자 번호가 잘못됐습니다")
        self.measurements.append(measurement)
        if len(self.measurements) % 100:
            return None
        return self._summary(self.measurements[-100:])

    def _summary(self, items: list[RoundMeasurement]) -> dict:
        if not items:
            raise ValueError("측정값이 없습니다")
        counts = {str(k): 0 for k in range(self.n)}
        for item in items:
            counts[str(item.slowest)] += 1
        normal = [item for item in items if not item.full]
        full = [item for item in items if item.full]
        return {
            "r_start": items[0].round, "r_end": items[-1].round, "count": len(items),
            "round_avg_ms": sum(item.round_ms for item in items) / len(items),
            "round_max_ms": max(item.round_ms for item in items),
            "wait_avg_ms": sum(item.wait_ms for item in items) / len(items),
            "wait_max_ms": max(item.wait_ms for item in items),
            "slowest_counts": counts,
            "normal_rounds": len(normal), "full_rounds": len(full),
            "normal_bytes": sum(item.bytes_sent_received for item in normal),
            "full_bytes": sum(item.bytes_sent_received for item in full),
        }

    def finish(self, elapsed_ms: float, handlers_joined: int) -> dict:
        if len(self.measurements) != 3000 or elapsed_ms <= 0 or handlers_joined != self.n:
            raise ValueError("전체 라운드와 작업자 종료를 확인해야 합니다")
        summary = self._summary(self.measurements)
        counts = summary["slowest_counts"]
        most = max(counts.values())
        summary.update({
            "rounds_completed": len(self.measurements), "elapsed_ms": elapsed_ms,
            "throughput_round_s": len(self.measurements) * 1000 / elapsed_ms,
            "handlers_joined": handlers_joined,
            "slowest_workers": [k for k in range(self.n) if counts[str(k)] == most],
            "normal_avg_bytes": summary["normal_bytes"] / summary["normal_rounds"],
            "full_avg_bytes": summary["full_bytes"] / summary["full_rounds"],
        })
        del summary["r_start"], summary["r_end"], summary["count"]
        return summary
