"""Synthetic geometry tests; real scanned column layouts still need verification."""
from app.services.ocr_layout import order_ocr_lines


def line(text, x, y, width=100):
    return {'text': text, 'bbox': [x, y, x + width, y + 10]}


def test_conservative_two_column_order_retains_all_lines_and_header():
    source = [line('Header', 50, 5, 500), line('Left 1', 30, 40), line('Right 1', 330, 46),
              line('Left 2', 30, 60), line('Right 2', 330, 66), line('Left 3', 30, 80),
              line('Right 3', 330, 86)]
    ordered, layout = order_ocr_lines(source, 600)
    assert layout == 'two_columns'
    assert [x['text'] for x in ordered] == ['Header', 'Left 1', 'Left 2', 'Left 3', 'Right 1', 'Right 2', 'Right 3']
    assert source[1]['text'] == 'Left 1' and len(source) == len(ordered)


def test_table_or_spanning_body_is_never_reordered():
    table = [line(f'{side}{i}', x, y) for i, y in enumerate([40, 60, 80]) for side, x in [('L', 30), ('R', 330)]]
    ordered, layout = order_ocr_lines(table, 600)
    assert layout == 'ambiguous' and ordered == table
    column = [line(f'L{i}', 30, y) for i, y in enumerate([40, 60, 80])] + [line(f'R{i}', 330, y) for i, y in enumerate([46, 66, 86])]
    column.append(line('section break', 50, 55, 500))
    ordered, layout = order_ocr_lines(column, 600)
    assert layout == 'ambiguous' and ordered == column
