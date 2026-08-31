"""项目内设计 DNA Skill 包的确定性校验测试。"""

import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PROJECT_ROOT / "ref" / "multimodal-design-dna-extractor"


class DnaSkillPackageTestCase(unittest.TestCase):
    def test_skill_package_and_examples_are_valid(self) -> None:
        package_check = subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / "validate_skill_package.py")],
            text=True,
            capture_output=True,
            cwd=PROJECT_ROOT,
            check=False,
        )
        self.assertEqual(package_check.returncode, 0, package_check.stderr)

        for example_name in ("smartphone-rear.example.json", "apparel.example.json"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_ROOT / "scripts" / "validate_output.py"),
                    str(SKILL_ROOT / "examples" / example_name),
                ],
                text=True,
                capture_output=True,
                cwd=PROJECT_ROOT,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
