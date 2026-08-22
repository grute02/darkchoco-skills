"""db_tree.py 행 수 집계 테스트.

    python -m unittest tools.test_db_tree -v
    python tools/test_db_tree.py

pytest 를 안 쓴다. 표준 라이브러리만으로 돈다.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db_tree  # noqa: E402

HERE = Path(__file__).resolve().parent
# 실물 재료. 케이스가 끝나면 지워지므로 없으면 건너뛴다.
REAL = Path.home() / "Documents" / "Q.E.D" / "화햇" / "화햇강의자료" / "프젝" / \
    "VM공유폴더" / "leak South korea" / "daouwood.co.kr"


def scan_sql(sql: str):
    """SQL 문자열을 임시 파일로 써서 scan 에 넣는다."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "dump.sql"
        p.write_text(sql, encoding="utf-8")
        return db_tree.scan(p)


class 행수집계(unittest.TestCase):
    def test_줄바꿈으로_나뉜_튜플을_센다(self):
        """phpMyAdmin 내보내기 형식. 튜플이 한 줄에 하나씩 온다."""
        sql = (
            "INSERT INTO `t` (`a`, `b`) VALUES\n"
            "(1, 'x'),\n"
            "(2, 'y'),\n"
            "(3, 'z');\n"
        )
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["t"], 3)

    def test_확장_INSERT_를_센다(self):
        """mysqldump 기본 형식. 한 줄에 튜플이 이어 붙는다."""
        sql = "INSERT INTO `t` VALUES (1,'x'),(2,'y'),(3,'z');\n"
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["t"], 3)

    def test_공백이_들어간_확장_INSERT_를_센다(self):
        sql = "INSERT INTO `t` VALUES (1,'x'), (2,'y'), (3,'z');\n"
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["t"], 3)

    def test_문장당_한_튜플을_센다(self):
        sql = (
            "INSERT INTO `t` VALUES (1,'x');\n"
            "INSERT INTO `t` VALUES (2,'y');\n"
            "INSERT INTO `t` VALUES (3,'z');\n"
        )
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["t"], 3)

    def test_한_줄에_INSERT_가_둘이면_각각_센다(self):
        """앞 문장의 집계 범위가 뒤 문장까지 넘어가면 중복으로 센다."""
        sql = "INSERT INTO `a` VALUES (1); INSERT INTO `b` VALUES (2),(3);\n"
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["a"], 1)
        self.assertEqual(rows["b"], 2)

    def test_표가_여럿이면_따로_센다(self):
        sql = (
            "INSERT INTO `a` (`x`) VALUES\n(1),\n(2);\n"
            "INSERT INTO `b` (`x`) VALUES\n(1),\n(2),\n(3);\n"
        )
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["a"], 2)
        self.assertEqual(rows["b"], 3)

    def test_값_안에_세미콜론이_있어도_뒤_튜플을_잃지_않는다(self):
        """읽기 버퍼는 세미콜론이 든 줄에서 비워진다.

        그래서 INSERT 헤더와 떨어진 자리에 남는 튜플이 생긴다.
        헤더가 앞 버퍼에 있었다는 것을 기억하지 않으면 그 줄들이 통째로 버려진다.
        """
        sql = (
            "INSERT INTO `t` (`a`) VALUES\n"
            "('세미콜론 ; 이 든 값'),\n"
            "('둘째 줄'),\n"
            "('셋째 줄');\n"
        )
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["t"], 3)

    def test_값_안에_괄호가_있어도_튜플로_세지_않는다(self):
        sql = (
            "INSERT INTO `t` (`a`) VALUES\n"
            "('여는 괄호 ( 가 든 값'),\n"
            "('닫는 괄호 ) 가 든 값');\n"
        )
        _, rows, _, _ = scan_sql(sql)
        self.assertEqual(rows["t"], 2)


class 집계방식표기(unittest.TestCase):
    def test_줄_단위_튜플이면_방식을_알려준다(self):
        sql = "INSERT INTO `t` (`a`) VALUES\n(1),\n(2);\n"
        *_, methods = scan_sql(sql)
        self.assertIn("줄 단위 튜플", methods)

    def test_확장_INSERT_면_방식을_알려준다(self):
        sql = "INSERT INTO `t` VALUES (1),(2);\n"
        *_, methods = scan_sql(sql)
        self.assertIn("확장 INSERT", methods)

    def test_문장당_한_튜플이면_방식을_알려준다(self):
        sql = "INSERT INTO `t` VALUES (1);\n"
        *_, methods = scan_sql(sql)
        self.assertIn("문장당 한 튜플", methods)

    def test_출력에_어림값_표기와_집계_방식이_함께_나온다(self):
        sql = "INSERT INTO `t` (`a`) VALUES\n(1),\n(2),\n(3);\n"
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "dump.sql"
            src.write_text(sql, encoding="utf-8")
            out = Path(d) / "구조.md"
            r = subprocess.run(
                [sys.executable, str(HERE / "db_tree.py"), str(src), "--md", str(out)],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            md = out.read_text(encoding="utf-8")
        self.assertIn("어림값", md)
        self.assertIn("줄 단위 튜플", md)
        self.assertIn("3", md)


@unittest.skipUnless(REAL.exists(), f"실물 재료 없음: {REAL}")
class 실물대조(unittest.TestCase):
    """같은 데이터의 CSV 사본이 옆에 있어 정답을 안다."""

    def test_cs_member_는_2691행이다(self):
        _, rows, _, _ = db_tree.scan(REAL / "cs_member.sql")
        self.assertEqual(rows["cs_member"], 2691)

    def test_cs_trade_는_4149행이다(self):
        _, rows, _, _ = db_tree.scan(REAL / "cs_trade.sql")
        self.assertEqual(rows["cs_trade"], 4149)


if __name__ == "__main__":
    unittest.main(verbosity=2)
