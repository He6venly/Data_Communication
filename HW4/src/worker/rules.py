RAMP = " .:-=+*#%@"
NEXT = dict(zip(RAMP, RAMP[1:] + RAMP[:1]))


def rule1_cell(w, i, x):
    # 주변에 살아 있는 칸이 몇 개인지 보고 다음 칸에 들어갈 문자를 정해줌
    width = len(w[0])
    left, right = (x - 1) % width, (x + 1) % width
    above, row, below = w[i - 1], w[i], w[i + 1]
    parents = [c for c in (above[left], above[x], above[right], row[left],
                           row[right], below[left], below[x], below[right]) if c != " "]
    if row[x] != " ":
        return row[x] if len(parents) in (2, 3) else " "
    if len(parents) != 3:
        return " "
    a, b, c = parents
    return a if a == b or a == c else b if b == c else min(parents)


def rule2_cell(w, i, x):
    # @는 +로, +는 공백으로 바꾸고 빈칸은 주변 @가 딱 2개일 때 @로 바꿈
    if w[i][x] == "@":
        return "+"
    if w[i][x] == "+":
        return " "
    width = len(w[0])
    left, right = (x - 1) % width, (x + 1) % width
    above, row, below = w[i - 1], w[i], w[i + 1]
    count = sum(c == "@" for c in (above[left], above[x], above[right], row[left],
                                   row[right], below[left], below[x], below[right]))
    return "@" if row[x] == " " and count == 2 else " "


def rule3_cell(w, i, x):
    # 위아래랑 양옆에 다음 밝기 문자가 있으면 그 문자로 바꿔줌
    current = w[i][x]
    target = NEXT[current]
    width = len(w[0])
    return target if target in (w[i - 1][x], w[i + 1][x],
                                w[i][(x - 1) % width], w[i][(x + 1) % width]) else current


def repaint(w, c):
    # 덧칠할 그림에서 공백이랑 점은 빼고 Halo까지 같이 덮어씀
    for row, paint in zip(w, c, strict=True):
        for x, char in enumerate(paint):
            if char not in " .":
                row[x] = char


def to_brian(w):
    # 작업판에서 공백이 아닌 칸은 전부 @로 바꿔줌
    for row in w:
        row[:] = ["@" if char != " " else " " for char in row]


def to_cyclic(w, ytop, team):
    # 전체 판에서의 행 번호로 밝기를 계산하고 이미 밝기 문자인 칸은 그대로 둠
    for i, row in enumerate(w):
        y = (ytop + i) % 80
        for x, char in enumerate(row):
            if char not in RAMP[1:]:
                row[x] = RAMP[(7 * x + 3 * y + (x * y) % 11 + team) % 10]
