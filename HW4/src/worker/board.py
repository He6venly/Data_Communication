from .rules import repaint, rule1_cell, rule2_cell, rule3_cell, to_brian, to_cyclic

HEIGHT, WIDTH, ROUNDS = 80, 160, 3000


class Board:
    def __init__(self, rows, canvas1, canvas2, y0, team):
        # 맡은 띠랑 덧칠할 조각만 저장하고 현재 상태랑 다음 상태를 따로 준비해둠
        self.h = len(rows)
        self.y0, self.team = y0, team
        width = len(rows[0])
        self.cur = [[" "] * width] + [list(row) for row in rows] + [[" "] * width]
        self.next = [[" "] * width for _ in range(self.h + 2)]
        self.canvas1 = [list(row) for row in canvas1]
        self.canvas2 = [list(row) for row in canvas2]
        self.round = 0

    def step(self, r, top, bottom):
        # 받은 Halo부터 넣고 규칙이 바뀌는 시점이면 변환한 다음 맡은 띠만 계산해줌
        if r != self.round or not 0 <= r < ROUNDS:
            raise ValueError("Round 순서가 잘못됐습니다")
        self.cur[0][:], self.cur[-1][:] = top, bottom
        if r == 1000:
            repaint(self.cur, self.canvas1)
            to_brian(self.cur)
        elif r == 2000:
            repaint(self.cur, self.canvas2)
            to_cyclic(self.cur, (self.y0 - 1) % HEIGHT, self.team)
        cell = (rule1_cell, rule2_cell, rule3_cell)[r // 1000]
        width = len(self.cur[0])
        for i in range(1, self.h + 1):
            self.next[i][:] = [cell(self.cur, i, x) for x in range(width)]
        self.cur, self.next = self.next, self.cur
        self.round += 1

    def rows(self):
        return ["".join(row) for row in self.cur[1:-1]]

    def result(self, r, k):
        # 매번 첫 줄이랑 마지막 줄을 보내고 10회마다 맡은 띠 전체도 같이 보냄
        rows = self.rows()
        lines = [f"RESULT {r} {k}", rows[0], rows[-1]]
        if (r + 1) % 10 == 0:
            lines.extend(rows)
        return ("\n".join(lines) + "\n").encode("ascii")
