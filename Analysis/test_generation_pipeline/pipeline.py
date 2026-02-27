#!/usr/bin/env python3
"""
Test Generation Pipeline
================================================
4-tier test generation pipeline for semantic equivalence testing.

Tier 1: Clone repos and extract tests from the actual project checkout
Tier 2: Broader repo tree search for related test files
Tier 3: Generate tests with Randoop
"""

import json
import logging
import os
import re
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier 1: Clone repos and extract tests from the project checkout
# ---------------------------------------------------------------------------

class TestExtractionPipeline:
    """
    Extract test methods from the actual project repo at each commit.

    For each commit in the dataset:
    1. Clone the Apache project repo (bare, cached per project)
    2. For each source file, compute candidate test file paths
    3. Use ``git show <sha>:<path>`` to retrieve test file contents
    4. Extract @Test / JUnit 3 methods from the test files
    """

    def __init__(self, output_dir: str = "tier1_extracted",
                 repos_dir: str = "repos"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.repos_dir = Path(repos_dir)
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self._cloned: Dict[str, Optional[Path]] = {}   # project -> repo_dir
        self.stats = {
            "commits_processed": 0,
            "files_checked": 0,
            "test_candidates_tried": 0,
            "test_files_found": 0,
            "test_methods_extracted": 0,
            "commits_with_zero_tests": 0,
            "clone_failures": 0,
        }
        self.all_tests: List[Dict] = []
        self.commits_without_tests: List[Dict] = []

    # ---- repo management (bare clone) --------------------------------

    def clone_repo(self, project: str) -> Optional[Path]:
        """Bare-clone the repo once per project; return the repo dir."""
        if project in self._cloned:
            return self._cloned[project]

        repo_dir = self.repos_dir / f"{project}.git"
        if repo_dir.exists():
            self._cloned[project] = repo_dir
            return repo_dir

        url = f"https://github.com/apache/{project}.git"
        logger.info("Cloning %s (bare) ...", url)
        try:
            r = subprocess.run(
                ["git", "clone", "--bare", url, str(repo_dir)],
                capture_output=True, text=True, timeout=600,
            )
            if r.returncode != 0:
                logger.warning("Clone failed for %s: %s", project,
                               r.stderr[:300])
                self.stats["clone_failures"] += 1
                self._cloned[project] = None
                return None
            self._cloned[project] = repo_dir
            return repo_dir
        except Exception as exc:
            logger.warning("Clone exception for %s: %s", project, exc)
            self.stats["clone_failures"] += 1
            self._cloned[project] = None
            return None

    def git_show(self, repo_dir: Path, sha: str,
                 filepath: str) -> Optional[str]:
        """Return file content at *sha* via ``git show``."""
        try:
            r = subprocess.run(
                ["git", "--git-dir", str(repo_dir), "show",
                 f"{sha}:{filepath}"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        return None

    def git_ls_tree(self, repo_dir: Path, sha: str,
                    prefix: str = "") -> List[str]:
        """List files at *sha*, optionally restricted to *prefix*."""
        cmd = ["git", "--git-dir", str(repo_dir),
               "ls-tree", "-r", "--name-only", sha]
        if prefix:
            cmd.extend(["--", prefix])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=60)
            if r.returncode != 0:
                return []
            return [l for l in r.stdout.strip().split("\n") if l]
        except Exception:
            return []

    # ---- test-file mapping -------------------------------------------

    @staticmethod
    def _find_test_candidates(source_file: str) -> List[str]:
        """
        Map a main source file to candidate test file paths.

        ``src/main/java/com/example/Foo.java``  →
          ``src/test/java/com/example/FooTest.java``, etc.
        """
        if "/src/main/" not in source_file:
            return []
        if not source_file.endswith(".java"):
            return []

        # replace src/main/... with src/test/...
        if "/src/main/java/" in source_file:
            test_base = source_file.replace("/src/main/java/",
                                            "/src/test/java/")
        else:
            test_base = source_file.replace("/src/main/", "/src/test/")

        stem = test_base[:-5]                       # strip .java
        candidates = [
            stem + "Test.java",
            stem + "Tests.java",
            stem + "IT.java",
            stem + "TestCase.java",
        ]
        # TestFoo.java pattern
        if "/" in stem:
            dir_part, base_part = stem.rsplit("/", 1)
            candidates.append(f"{dir_part}/Test{base_part}.java")

        return candidates

    @staticmethod
    def is_test_file(file_path: str) -> bool:
        """Determine whether *file_path* looks like a Java test file."""
        if "/src/test/java/" in file_path or "/src/test/" in file_path:
            return True
        basename = Path(file_path).name
        if basename.endswith("Test.java") or basename.endswith("Tests.java"):
            return True
        if basename.startswith("Test") and basename.endswith(".java"):
            return True
        if basename.endswith("IT.java"):
            return True
        return False

    # ---- extraction helpers ------------------------------------------

    @staticmethod
    def _extract_method_body(content: str, brace_pos: int) -> str:
        """Return text between matching braces starting at *brace_pos*."""
        depth, i = 1, brace_pos + 1
        while i < len(content) and depth > 0:
            ch = content[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        return content[brace_pos + 1 : i - 1] if depth == 0 else ""

    def extract_test_methods(self, file_content: str,
                             file_path: str) -> List[Dict]:
        """Extract @Test / JUnit-3/4 test methods from *file_content*."""
        tests: List[Dict] = []
        seen: set = set()

        try:
            # JUnit 4 / 5 — @Test 
            pat4 = re.compile(
                r'(@Test[^\n]*\n\s*)'
                r'(?:public|protected|private)?\s*'
                r'(?:static\s+)?'
                r'\w[\w<>,\s]*\s+'
                r'(\w+)\s*'
                r'\([^)]*\)\s*'
                r'(?:throws\s+[\w,\s]+)?\s*\{',
                re.MULTILINE,
            )
            for m in pat4.finditer(file_content):
                mname = m.group(2)
                if mname in seen:
                    continue
                seen.add(mname)
                body = self._extract_method_body(file_content, m.end() - 1)
                if body:
                    tests.append({
                        "method_name": mname,
                        "code": file_content[m.start():m.end() - 1 + len(body) + 1],
                        "file_path": file_path,
                        "annotation": "@Test",
                    })

            # JUnit 3 — extends TestCase
            if "extends TestCase" in file_content:
                pat3 = re.compile(
                    r'(?:public|protected)\s+void\s+'
                    r'(test\w+)\s*'
                    r'\([^)]*\)\s*'
                    r'(?:throws\s+[\w,\s]+)?\s*\{',
                    re.MULTILINE,
                )
                for m in pat3.finditer(file_content):
                    mname = m.group(1)
                    if mname in seen:
                        continue
                    seen.add(mname)
                    body = self._extract_method_body(file_content, m.end() - 1)
                    if body:
                        tests.append({
                            "method_name": mname,
                            "code": file_content[m.start():m.end() - 1 + len(body) + 1],
                            "file_path": file_path,
                            "annotation": "extends TestCase",
                        })
        except Exception as exc:
            logger.debug("extract error %s: %s", file_path, exc)

        return tests

    @staticmethod
    def extract_package(content: str) -> Optional[str]:
        m = re.search(r"package\s+([\w.]+)\s*;", content)
        return m.group(1) if m else None

    @staticmethod
    def extract_classname(content: str, file_path: str) -> str:
        m = re.search(
            r'(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)',
            content,
        )
        return m.group(1) if m else Path(file_path).stem

    # ---- per-commit processing ---------------------------------------

    def process_commit(self, commit_data: Dict) -> Dict:
        project = commit_data["project"]
        sha = commit_data["commit_sha"]
        files = commit_data.get("files", [])

        result = {
            "project": project,
            "commit_sha": sha,
            "files_checked": 0,
            "test_files_found": 0,
            "test_methods": 0,
            "extracted": [],
        }

        repo_dir = self.clone_repo(project)
        if repo_dir is None:
            return result

        seen_test_paths: set = set()

        for fdata in files:
            fpath = fdata.get("file_name", "")
            if not fpath or not fpath.endswith(".java"):
                continue
            result["files_checked"] += 1

            # Build list of candidate test file paths
            candidates: List[str] = []
            if self.is_test_file(fpath):
                # File is itself a test file — retrieve from repo
                candidates.append(fpath)
            else:
                # Main source file → derive test candidates
                candidates = self._find_test_candidates(fpath)

            for cand in candidates:
                if cand in seen_test_paths:
                    continue
                seen_test_paths.add(cand)
                self.stats["test_candidates_tried"] += 1

                content = self.git_show(repo_dir, sha, cand)
                if not content:
                    continue

                result["test_files_found"] += 1
                self.stats["test_files_found"] += 1

                methods = self.extract_test_methods(content, cand)
                if not methods:
                    continue

                pkg = self.extract_package(content)
                cname = self.extract_classname(content, cand)

                for t in methods:
                    t.update({
                        "project": project,
                        "commit_sha": sha,
                        "package": pkg,
                        "class_name": cname,
                        "fqcn": f"{pkg}.{cname}" if pkg else cname,
                    })
                    result["extracted"].append(t)
                    result["test_methods"] += 1

        return result

    # ---- dataset-level processing ------------------------------------

    def process_dataset(self, dataset_path: str,
                        limit: Optional[int] = None) -> Dict:
        logger.info("=" * 70)
        logger.info("TIER 1: EXTRACT TESTS FROM REPO CHECKOUT")
        logger.info("=" * 70)

        all_results: List[Dict] = []
        with open(dataset_path) as fh:
            for idx, line in enumerate(fh, 1):
                if limit and idx > limit:
                    break
                try:
                    cdata = json.loads(line)
                except json.JSONDecodeError:
                    continue

                result = self.process_commit(cdata)
                all_results.append(result)

                self.stats["commits_processed"] += 1
                self.stats["files_checked"] += result["files_checked"]
                self.stats["test_methods_extracted"] += result["test_methods"]

                if result["test_methods"] == 0:
                    self.stats["commits_with_zero_tests"] += 1
                    self.commits_without_tests.append({
                        "project": cdata["project"],
                        "commit_sha": cdata["commit_sha"],
                        "files": cdata.get("files", []),
                    })

                self.all_tests.extend(result["extracted"])

                if idx % 100 == 0:
                    logger.info(
                        "[%d] running total: %d tests from %d test files",
                        idx,
                        self.stats["test_methods_extracted"],
                        self.stats["test_files_found"],
                    )

        # persist
        (self.output_dir / "extraction_results.json").write_text(
            json.dumps({"stats": self.stats, "results": all_results},
                       indent=2)
        )
        (self.output_dir / "commits_without_tests.json").write_text(
            json.dumps(
                [{"project": c["project"], "commit_sha": c["commit_sha"]}
                 for c in self.commits_without_tests],
                indent=2,
            )
        )
        (self.output_dir / "extracted_tests.json").write_text(
            json.dumps(self.all_tests, indent=2)
        )

        logger.info("-" * 70)
        logger.info("Tier 1 results:")
        logger.info("  Commits processed       : %d",
                     self.stats["commits_processed"])
        logger.info("  Files checked           : %d",
                     self.stats["files_checked"])
        logger.info("  Test candidates tried   : %d",
                     self.stats["test_candidates_tried"])
        logger.info("  Test files found        : %d",
                     self.stats["test_files_found"])
        logger.info("  Test methods extracted   : %d",
                     self.stats["test_methods_extracted"])
        logger.info("  Commits with ZERO tests : %d",
                     self.stats["commits_with_zero_tests"])
        logger.info("  Clone failures          : %d",
                     self.stats["clone_failures"])
        logger.info("-" * 70)

        return {
            "tier": 1,
            "stats": self.stats,
            "tests": self.all_tests,
            "commits_without_tests": self.commits_without_tests,
        }


# ---------------------------------------------------------------------------
# Tier 2: Broader repo tree search for related test files
# ---------------------------------------------------------------------------

class DoubleCheckExtraction:
    """
    Second pass for commits with zero tests after Tier 1.

    Uses ``git ls-tree`` to find ALL test files in the same packages as
    the modified source files and extracts any tests discovered.
    """

    def __init__(self, output_dir: str = "tier2_doublecheck"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"checked": 0, "recovered": 0, "methods_recovered": 0}
        self.recovered_tests: List[Dict] = []

    @staticmethod
    def _test_prefix_for_source(source_file: str) -> Optional[str]:
        """
        Convert a main-source path to its test-directory prefix.

        ``components/camel-smpp/src/main/java/org/apache/camel/component/smpp/Foo.java``
          → ``components/camel-smpp/src/test/java/org/apache/camel/component/smpp/``
        """
        if "/src/main/java/" in source_file:
            base = source_file.replace("/src/main/java/", "/src/test/java/")
        elif "/src/main/" in source_file:
            base = source_file.replace("/src/main/", "/src/test/")
        else:
            return None
        # strip filename, keep directory
        idx = base.rfind("/")
        return base[: idx + 1] if idx >= 0 else None

    def check_commits(
        self,
        commits_without_tests: List[Dict],
        extractor: TestExtractionPipeline,
    ) -> Dict:
        logger.info("=" * 70)
        logger.info("TIER 2: DOUBLE-CHECK (repo tree search)")
        logger.info("=" * 70)

        for commit in commits_without_tests:
            self.stats["checked"] += 1
            project = commit["project"]
            sha = commit["commit_sha"]

            repo_dir = extractor.clone_repo(project)
            if repo_dir is None:
                continue

            # Collect unique test-directory prefixes from source files
            prefixes: set = set()
            for fdata in commit.get("files", []):
                fpath = fdata.get("file_name", "")
                if not fpath.endswith(".java"):
                    continue
                if extractor.is_test_file(fpath):
                    # already a test file — was tried in Tier 1
                    continue
                pfx = self._test_prefix_for_source(fpath)
                if pfx:
                    prefixes.add(pfx)

            if not prefixes:
                continue

            found_any = False
            seen_paths: set = set()

            for pfx in prefixes:
                # list test files in this package directory at the commit
                tree_files = extractor.git_ls_tree(repo_dir, sha,
                                                   prefix=pfx)
                for tf in tree_files:
                    if tf in seen_paths:
                        continue
                    if not extractor.is_test_file(tf):
                        continue
                    seen_paths.add(tf)

                    content = extractor.git_show(repo_dir, sha, tf)
                    if not content:
                        continue

                    methods = extractor.extract_test_methods(content, tf)
                    if not methods:
                        continue

                    found_any = True
                    pkg = extractor.extract_package(content)
                    cname = extractor.extract_classname(content, tf)
                    for t in methods:
                        t.update({
                            "project": project,
                            "commit_sha": sha,
                            "package": pkg,
                            "class_name": cname,
                            "fqcn": f"{pkg}.{cname}" if pkg else cname,
                            "tier": 2,
                        })
                        self.recovered_tests.append(t)
                        self.stats["methods_recovered"] += 1

            if found_any:
                self.stats["recovered"] += 1

        (self.output_dir / "doublecheck_results.json").write_text(
            json.dumps({"stats": self.stats,
                        "tests": self.recovered_tests}, indent=2)
        )

        logger.info("-" * 70)
        logger.info("Tier 2 results:")
        logger.info("  Commits re-checked    : %d", self.stats["checked"])
        logger.info("  Commits recovered     : %d", self.stats["recovered"])
        logger.info("  Methods recovered     : %d",
                     self.stats["methods_recovered"])
        logger.info("-" * 70)

        return {
            "tier": 2,
            "stats": self.stats,
            "tests": self.recovered_tests,
        }


# ---------------------------------------------------------------------------
# Tier 3: Automated test generation (EvoSuite with Randoop fallback)
# ---------------------------------------------------------------------------

class EvoSuiteTestGenerator:
    """Generate tests with EvoSuite."""

    def __init__(self, output_dir: str = "tier3_evosuite", tools_dir: str = "../tools"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        script_dir = Path(__file__).parent
        self.tools_dir = (script_dir / tools_dir).resolve()
        self.evosuite_jar = self._ensure_evosuite()
        self.java_home   = self._find_java()
        self.maven_cmd   = self._find_maven()
        self.stats = {
            "commits_attempted": 0,
            "commits_cloned": 0,
            "commits_compiled": 0,
            "tests_generated": 0,
            "failures": 0,
        }

    def _ensure_evosuite(self) -> Path:
        """Ensure EvoSuite JAR is available."""
        jar = self.tools_dir / "evosuite-1.2.0.jar"
        if jar.exists():
            return jar
        jar = Path("../evosuite-1.2.0.jar")
        if jar.exists():
            return jar
        logger.warning("EvoSuite JAR not found at %s", jar)
        return jar

    def _find_java(self) -> Path:
        """Find Java installation. Prefers local JDK, then JAVA_HOME, then system."""
        for name in ("jdk8", "jdk11"):
            p = self.tools_dir / name
            if p.exists() and (p / "bin" / "java").exists():
                logger.debug("Using local JDK: %s", p)
                return p

        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            p = Path(java_home)
            if p.exists() and (p / "bin" / "java").exists():
                logger.debug("Using JAVA_HOME: %s", p)
                return p

        try:
            result = subprocess.run(["which", "java"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                java_home = Path(result.stdout.strip()).parent.parent
                logger.debug("Using system Java: %s", java_home)
                return java_home
        except Exception:
            pass

        raise FileNotFoundError("Java not found in tools, JAVA_HOME, or system")

    def _find_maven(self) -> str:
        """Find Maven installation. Returns command string."""
        p = self.tools_dir / "apache-maven-3.6.3" / "bin" / "mvn"
        if p.exists():
            logger.debug("Using local Maven: %s", p)
            return str(p)

        try:
            result = subprocess.run(["which", "mvn"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                mvn_path = result.stdout.strip()
                logger.debug("Using system Maven: %s", mvn_path)
                return mvn_path
        except Exception:
            pass

        logger.warning("Maven not found, assuming 'mvn' is in PATH")
        return "mvn"

    def clone_and_checkout(self, project: str, sha: str) -> Optional[Path]:
        """Clone the repository and checkout specific commit."""
        repo_dir = self.output_dir / "repos" / project

        if repo_dir.exists():
            try:
                subprocess.run(
                    ["git", "clean", "-fdx", "-e", ".git"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=60,
                )
                subprocess.run(
                    ["git", "checkout", "-f", sha],
                    cwd=repo_dir, capture_output=True, text=True, timeout=30,
                )
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip().startswith(sha[:8]):
                    logger.debug("Reused existing repo, checked out %s (verified)", sha[:8])
                    return repo_dir
                else:
                    logger.warning("Checkout failed in existing repo, will re-clone")
                    shutil.rmtree(repo_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("Error reusing repo: %s, will re-clone", e)
                shutil.rmtree(repo_dir, ignore_errors=True)

        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/apache/{project}.git"

        try:
            logger.info("Cloning %s (full history for commit %s)", project, sha[:8])
            result = subprocess.run(
                ["git", "clone", "--no-single-branch", url, str(repo_dir)],
                capture_output=True, text=True, timeout=600,
            )
            
            if result.returncode != 0:
                logger.error("Git clone failed: %s", result.stderr[:500])
                if repo_dir.exists():
                    shutil.rmtree(repo_dir, ignore_errors=True)
                return None

            result = subprocess.run(
                ["git", "checkout", sha],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )

            if result.returncode != 0:
                logger.error("Git checkout failed for %s: %s", sha[:8], result.stderr[:200])
                if repo_dir.exists():
                    shutil.rmtree(repo_dir, ignore_errors=True)
                return None

            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_dir, capture_output=True, text=True, timeout=5,
            )

            if result.returncode == 0:
                actual_sha = result.stdout.strip()
                if not actual_sha.startswith(sha[:8]):
                    logger.error("Checkout verification failed! Expected %s, got %s", sha[:8], actual_sha[:8])
                    if repo_dir.exists():
                        shutil.rmtree(repo_dir, ignore_errors=True)
                    return None
                logger.debug("Cloned and checked out %s at %s (verified)", project, sha[:8])
            else:
                logger.warning("Could not verify checkout, but proceeding")
                
            return repo_dir
            
        except subprocess.TimeoutExpired:
            logger.error("Git operation timeout for %s", project)
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            return None
        except Exception as e:
            logger.error("Clone/checkout failed: %s", e)
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            return None

    def _find_root_pom(self, repo_dir: Path) -> Optional[Path]:
        """Find the top-level pom.xml file."""
        root_pom = repo_dir / "pom.xml"
        if root_pom.exists():
            logger.debug("Found root pom.xml at %s", root_pom.relative_to(repo_dir))
            return root_pom

        all_poms = list(repo_dir.glob("**/pom.xml"))
        if all_poms:
            root_pom = min(all_poms, key=lambda p: len(p.parts))
            logger.debug("Using pom.xml at %s", root_pom.relative_to(repo_dir))
            return root_pom

        return None

    def _extract_module_from_files(self, commit: Dict) -> Optional[str]:
        """Extract the Maven module path from the file paths in the commit data."""
        files = commit.get("files", [])
        modules = set()
        for f in files:
            fname = f.get("file_name", "")
            for marker in ("src/main/java", "src/test/java", "src/main/resources"):
                idx = fname.find(marker)
                if idx > 0:
                    module_path = fname[:idx].rstrip("/")
                    if module_path:
                        modules.add(module_path)
                    break

        if modules:
            module = min(modules, key=len)
            logger.debug("Detected Maven module from file paths: %s", module)
            return module
        return None

    def _install_maven_plugins(self, compile_dir: Path, mvn: str,
                                skip_flags: List[str], env: dict) -> None:
        """Find and install custom Maven plugin modules in the project."""
        try:
            for pom_path in compile_dir.glob("**/pom.xml"):
                rel = pom_path.relative_to(compile_dir)
                if len(rel.parts) > 5:
                    continue
                try:
                    content = pom_path.read_text(errors="ignore")
                except Exception:
                    continue
                if "<packaging>maven-plugin</packaging>" in content:
                    logger.debug("Installing Maven plugin module: %s",
                                pom_path.parent.relative_to(compile_dir))
                    subprocess.run(
                        [mvn, "install", "-f", str(pom_path)] + skip_flags,
                        cwd=compile_dir, capture_output=True, text=True,
                        timeout=180, env=env,
                    )
        except Exception as e:
            logger.debug("Error scanning for Maven plugins: %s", e)

    def compile_project(self, repo_dir: Path, commit: Optional[Dict] = None) -> Tuple[bool, Optional[str]]:
        """Compile the project using Apache Maven.
        
        If commit data with file paths is available, compiles only the specific
        module (-pl <module> -am) instead of the entire project.
        """
        root_pom = self._find_root_pom(repo_dir)
        if not root_pom:
            logger.error("No pom.xml found in repository")
            return False, None

        compile_dir = root_pom.parent
        env = os.environ.copy()
        if self.java_home != Path("/usr"):
            env["JAVA_HOME"] = str(self.java_home.resolve())
            env["PATH"] = str(self.java_home / "bin") + ":" + env.get("PATH", "")
            logger.debug("Set JAVA_HOME=%s", env["JAVA_HOME"])
        mvn = self.maven_cmd

        target_module = None
        if commit:
            target_module = self._extract_module_from_files(commit)

        skip_flags = [
            "-DskipTests", "-Dmaven.test.skip=true",
            "-Dmaven.javadoc.skip=true", "-Dcheckstyle.skip=true",
            "-Denforcer.skip=true", "-Drat.skip=true",
            "-Dpmd.skip=true", "-Dspotbugs.skip=true",
            "-Dfindbugs.skip=true", "-Danimal.sniffer.skip=true",
            "-fn", "-B", "-U",
        ]

        try:
            logger.debug("Installing root POM...")
            subprocess.run(
                [mvn, "install", "-N"] + skip_flags,
                cwd=compile_dir, capture_output=True, text=True,
                timeout=120, env=env,
            )

            if target_module:
                tooling_dirs = ["tooling", "buildtools", "build-tools", "parent",
                                "tooling/maven", "build"]
                for tooling in tooling_dirs:
                    tooling_pom = compile_dir / tooling / "pom.xml"
                    if tooling_pom.exists():
                        logger.debug("Pre-installing build tooling: %s", tooling)
                        subprocess.run(
                            [mvn, "install", "-N", "-f", str(tooling_pom)] + skip_flags,
                            cwd=compile_dir, capture_output=True, text=True,
                            timeout=120, env=env,
                        )
                        subprocess.run(
                            [mvn, "install", "-f", str(tooling_pom)] + skip_flags,
                            cwd=compile_dir, capture_output=True, text=True,
                            timeout=300, env=env,
                        )

                self._install_maven_plugins(compile_dir, mvn, skip_flags, env)

            maven_goal = "install" if target_module else "compile"
            maven_flags = [mvn, maven_goal] + skip_flags
            
            if target_module:
                module_pom = compile_dir / target_module / "pom.xml"
                if module_pom.exists():
                    maven_flags.extend(["-pl", target_module, "-am"])
                    logger.debug("Installing specific module: %s (with dependencies)", target_module)
                else:
                    logger.warning("Module pom.xml not found at %s, compiling entire project", module_pom)
            else:
                logger.debug("No specific module detected, compiling entire project...")
            
            result = subprocess.run(
                maven_flags,
                cwd=compile_dir,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )

            search_dir = (compile_dir / target_module) if target_module else compile_dir
            classes_dirs = list(search_dir.glob("**/target/classes"))

            if not classes_dirs and target_module:
                logger.warning("Module-specific compilation produced no classes, trying full project...")
                fallback_flags = [mvn, "install"] + skip_flags
                result = subprocess.run(
                    fallback_flags,
                    cwd=compile_dir,
                    capture_output=True, text=True,
                    timeout=600, env=env,
                )
                classes_dirs = list(search_dir.glob("**/target/classes"))
            
            if not classes_dirs:
                logger.error("No target/classes directories found after compilation")
                stdout_lines = result.stdout.strip().split("\n")
                error_lines = [l for l in stdout_lines if "ERROR" in l or "FATAL" in l]
                if error_lines:
                    logger.error("Maven errors: %s", "\n".join(error_lines[:10]))
                logger.error("Maven exit code: %d", result.returncode)
                return False, None

            logger.debug("Compiled successfully, found %d target/classes directories", len(classes_dirs))

            cp_dir = (compile_dir / target_module) if target_module else compile_dir
            cp_pom = cp_dir / "pom.xml"
            
            if cp_pom.exists():
                result = subprocess.run(
                    [mvn, "dependency:build-classpath", "-DincludeScope=compile",
                     "-Dmdep.outputFile=/dev/stdout", "-q",
                     "-f", str(cp_pom.resolve()), "-B"],
                    cwd=str(compile_dir),
                    capture_output=True,
                    text=True,
                    timeout=180,
                    env=env,
                )

                if result.returncode == 0 and result.stdout.strip():
                    dep_cp = result.stdout.strip()
                    cp_parts = [str(d) for d in classes_dirs]
                    if dep_cp:
                        cp_parts.append(dep_cp)
                    full_cp = ":".join(cp_parts)
                    logger.debug("Classpath retrieved successfully (%d dirs + deps)", len(classes_dirs))
                    return True, full_cp

            classpath = ":".join(str(d) for d in classes_dirs)
            logger.warning("Using fallback classpath: %d target/classes dirs only", len(classes_dirs))
            return True, classpath

        except subprocess.TimeoutExpired:
            logger.error("Maven compilation timeout")
            return False, None
        except Exception as e:
            logger.error("Compilation error: %s", e)
            return False, None

    def collect_compiled_classes(self, repo_dir: Path) -> List[str]:
        """Collect all compiled class names from the project."""
        classes = []
        classes_dirs = list(repo_dir.glob("**/target/classes"))
        if not classes_dirs:
            logger.warning("No target/classes directories found in %s", repo_dir)
            return []

        logger.debug("Scanning %d target/classes directories", len(classes_dirs))
        for classes_dir in classes_dirs:
            for class_file in classes_dir.rglob("*.class"):
                try:
                    rel = str(class_file.relative_to(classes_dir))
                    class_name = rel[:-6].replace("/", ".")
                    if "$" in class_name or "Test" in class_name:
                        continue
                    classes.append(class_name)
                except Exception as e:
                    logger.debug("Error processing class file %s: %s", class_file, e)

        logger.debug("Found %d compiled classes across all modules", len(classes))
        return classes

    def generate_tests_evosuite(self, project: str, sha: str, classpath: str,
                                classes: List[str], out_dir: Path) -> int:
        """Generate tests with EvoSuite directly against compiled classes."""
        if not self.evosuite_jar.exists():
            logger.warning("EvoSuite JAR not found")
            return 0

        java = str(self.java_home / "bin" / "java")
        tests_generated = 0

        for class_name in classes:
            try:
                logger.debug("EvoSuite: generating tests for %s", class_name)
                result = subprocess.run(
                    [java, "-jar", str(self.evosuite_jar),
                     "-class", class_name,
                     "-projectCP", classpath,
                     "-Dsearch_budget", "60",
                     "-Dassertion_strategy", "all",
                     "-Dtest_dir", str(out_dir),
                     "-Dtest_comments", "false"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                if result.returncode == 0:
                    test_files = list(out_dir.glob("**/*_ESTest.java"))
                    if test_files:
                        tests_generated = len(test_files)
                        logger.debug("Generated %d EvoSuite test files", tests_generated)
                        break
                else:
                    combined = (result.stdout + result.stderr).strip()
                    if "Fatal crash" in combined or "NullPointerException" in combined:
                        logger.warning("EvoSuite fatal crash on %s", class_name)
                        break
                    logger.warning("EvoSuite returned code %d for %s", result.returncode, class_name)
            except subprocess.TimeoutExpired:
                logger.warning("Timeout generating tests for %s", class_name)
            except Exception as e:
                logger.warning("Error generating tests for %s: %s", class_name, e)

        return tests_generated

    def _extract_target_classes(self, commit: Dict) -> List[str]:
        """Extract fully-qualified class names from the commit's file paths."""
        classes = []
        files = commit.get("files", [])
        for f in files:
            fname = f.get("file_name", "")
            marker = "src/main/java/"
            idx = fname.find(marker)
            if idx >= 0 and fname.endswith(".java"):
                rel = fname[idx + len(marker):]
                class_name = rel[:-5].replace("/", ".")
                classes.append(class_name)
        return classes

    def generate_for_commit(self, commit: Dict) -> Dict:
        """Generate tests for a single commit using EvoSuite."""
        project, sha = commit["project"], commit["commit_sha"]
        result = {
            "project": project,
            "commit_sha": sha,
            "tests_generated": 0,
            "tool": "evosuite",
            "status": "failed"
        }

        repo = self.clone_and_checkout(project, sha)
        if not repo:
            logger.error("Failed to clone repository")
            self.stats["failures"] += 1
            return result
        self.stats["commits_cloned"] += 1

        success, classpath = self.compile_project(repo, commit)
        if not success or not classpath:
            logger.error("Failed to compile project")
            self.stats["failures"] += 1
            return result
        self.stats["commits_compiled"] += 1

        target_classes = self._extract_target_classes(commit)
        if target_classes:
            logger.debug("Targeting %d specific classes from commit: %s", 
                        len(target_classes), ", ".join(target_classes))
            classes = target_classes
        else:
            classes = self.collect_compiled_classes(repo)
            if not classes:
                logger.error("No compiled classes found")
                self.stats["failures"] += 1
                return result

        out_dir = self.output_dir / f"{project}_{sha[:8]}_tests"
        out_dir.mkdir(exist_ok=True)

        tests_generated = self.generate_tests_evosuite(project, sha, classpath, classes, out_dir)

        if tests_generated > 0:
            result["tests_generated"] = tests_generated
            result["status"] = "success"
            self.stats["tests_generated"] += tests_generated
        else:
            result["status"] = "no_tests"

        return result

    def process_commits(self, commits: List[Dict]) -> Dict:
        logger.info("=" * 70)
        logger.info("TIER 3a: EVOSUITE TEST GENERATION")
        logger.info("=" * 70)
        logger.info("Commits to process: %d", len(commits))

        results = []
        for idx, c in enumerate(commits, 1):
            self.stats["commits_attempted"] += 1
            logger.info(
                "[%d/%d] %s/%s", idx, len(commits),
                c["project"], c["commit_sha"][:8],
            )
            r = self.generate_for_commit(c)
            results.append(r)

        (self.output_dir / "evosuite_results.json").write_text(
            json.dumps({"stats": self.stats, "results": results}, indent=2)
        )

        logger.info("-" * 70)
        logger.info("Tier 3a EvoSuite results:")
        logger.info("  Attempted : %d", self.stats["commits_attempted"])
        logger.info("  Cloned    : %d", self.stats["commits_cloned"])
        logger.info("  Compiled  : %d", self.stats["commits_compiled"])
        logger.info("  Generated : %d", self.stats["tests_generated"])
        logger.info("  Failures  : %d", self.stats["failures"])
        logger.info("-" * 70)

        return {"tier": "3a", "stats": self.stats, "results": results}


class RandoopTestGenerator:
    """Generate tests with Randoop as fallback when EvoSuite fails."""

    def __init__(self, output_dir: str = "tier3b_randoop", tools_dir: str = "../tools"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        script_dir = Path(__file__).parent
        self.tools_dir = (script_dir / tools_dir).resolve()
        self.randoop_jar = self._ensure_randoop()
        self.java_home   = self._find_java()
        self.maven_cmd   = self._find_maven()
        self.stats = {
            "commits_attempted": 0,
            "commits_cloned": 0,
            "commits_compiled": 0,
            "tests_generated": 0,
            "failures": 0,
        }

    def _ensure_randoop(self) -> Path:
        jar = self.tools_dir / "randoop-all-4.3.2.jar"
        if jar.exists():
            return jar
        logger.info("Downloading Randoop 4.3.2 ...")
        import urllib.request
        jar.parent.mkdir(parents=True, exist_ok=True)
        url = "https://github.com/randoop/randoop/releases/download/v4.3.2/randoop-all-4.3.2.jar"
        try:
            urllib.request.urlretrieve(url, str(jar))
            logger.info("Downloaded %s (%.1f MB)", jar, jar.stat().st_size / 1e6)
        except Exception as e:
            logger.error("Failed to download Randoop: %s", e)
        return jar

    def _find_java(self) -> Path:
        """Find Java installation. Prefers local JDK, then JAVA_HOME, then system."""
        for name in ("jdk8", "jdk11"):
            p = self.tools_dir / name
            if p.exists() and (p / "bin" / "java").exists():
                logger.debug("Using local JDK: %s", p)
                return p

        java_home = os.environ.get("JAVA_HOME")
        if java_home:
            p = Path(java_home)
            if p.exists() and (p / "bin" / "java").exists():
                logger.debug("Using JAVA_HOME: %s", p)
                return p

        try:
            result = subprocess.run(["which", "java"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                java_home = Path(result.stdout.strip()).parent.parent
                logger.debug("Using system Java: %s", java_home)
                return java_home
        except Exception:
            pass

        raise FileNotFoundError("Java not found in tools, JAVA_HOME, or system")

    def _find_maven(self) -> str:
        """Find Maven installation. Returns command string."""
        p = self.tools_dir / "apache-maven-3.6.3" / "bin" / "mvn"
        if p.exists():
            logger.debug("Using local Maven: %s", p)
            return str(p)

        try:
            result = subprocess.run(["which", "mvn"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                mvn_path = result.stdout.strip()
                logger.debug("Using system Maven: %s", mvn_path)
                return mvn_path
        except Exception:
            pass

        logger.warning("Maven not found, assuming 'mvn' is in PATH")
        return "mvn"

    def _find_root_pom(self, repo_dir: Path) -> Optional[Path]:
        """Find the top-level pom.xml file."""
        root_pom = repo_dir / "pom.xml"
        if root_pom.exists():
            return root_pom

        all_poms = list(repo_dir.glob("**/pom.xml"))
        if all_poms:
            return min(all_poms, key=lambda p: len(p.parts))

        return None

    def clone_and_checkout(self, project: str, sha: str) -> Optional[Path]:
        """Clone the repository and checkout specific commit."""
        repo_dir = self.output_dir / "repos" / project

        if repo_dir.exists():
            try:
                subprocess.run(
                    ["git", "clean", "-fdx", "-e", ".git"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=60,
                )
                subprocess.run(
                    ["git", "checkout", "-f", sha],
                    cwd=repo_dir, capture_output=True, text=True, timeout=30,
                )
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip().startswith(sha[:8]):
                    logger.debug("Reused existing repo, checked out %s (verified)", sha[:8])
                    return repo_dir
                else:
                    logger.warning("Checkout failed in existing repo, will re-clone")
                    shutil.rmtree(repo_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("Error reusing repo: %s, will re-clone", e)
                shutil.rmtree(repo_dir, ignore_errors=True)

        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/apache/{project}.git"

        try:
            logger.info("Cloning %s (full history for commit %s)", project, sha[:8])
            result = subprocess.run(
                ["git", "clone", "--no-single-branch", url, str(repo_dir)],
                capture_output=True, text=True, timeout=600,
            )

            if result.returncode != 0:
                logger.error("Git clone failed: %s", result.stderr[:500])
                if repo_dir.exists():
                    shutil.rmtree(repo_dir, ignore_errors=True)
                return None

            result = subprocess.run(
                ["git", "checkout", sha],
                cwd=repo_dir, capture_output=True, text=True, timeout=30,
            )

            if result.returncode != 0:
                logger.error("Git checkout failed for %s: %s", sha[:8], result.stderr[:200])
                if repo_dir.exists():
                    shutil.rmtree(repo_dir, ignore_errors=True)
                return None

            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_dir, capture_output=True, text=True, timeout=5,
            )

            if result.returncode == 0:
                actual_sha = result.stdout.strip()
                if not actual_sha.startswith(sha[:8]):
                    logger.error("Checkout verification failed! Expected %s, got %s", sha[:8], actual_sha[:8])
                    if repo_dir.exists():
                        shutil.rmtree(repo_dir, ignore_errors=True)
                    return None
                logger.debug("Cloned and checked out %s at %s (verified)", project, sha[:8])
            else:
                logger.warning("Could not verify checkout, but proceeding")
                
            return repo_dir
            
        except subprocess.TimeoutExpired:
            logger.error("Git operation timeout for %s", project)
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            return None
        except Exception as e:
            logger.error("Clone/checkout failed: %s", e)
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            return None

    def _extract_module_from_files(self, commit: Dict) -> Optional[str]:
        """Extract the Maven module path from file paths in the commit data."""
        files = commit.get("files", [])
        modules = set()
        for f in files:
            fname = f.get("file_name", "")
            for marker in ("src/main/java", "src/test/java", "src/main/resources"):
                idx = fname.find(marker)
                if idx > 0:
                    module_path = fname[:idx].rstrip("/")
                    if module_path:
                        modules.add(module_path)
                    break
        if modules:
            module = min(modules, key=len)
            logger.debug("Detected Maven module from file paths: %s", module)
            return module
        return None

    def _install_maven_plugins(self, compile_dir: Path, mvn: str,
                                skip_flags: List[str], env: dict) -> None:
        """Find and install custom Maven plugin modules in the project."""
        try:
            for pom_path in compile_dir.glob("**/pom.xml"):
                rel = pom_path.relative_to(compile_dir)
                if len(rel.parts) > 5:
                    continue
                try:
                    content = pom_path.read_text(errors="ignore")
                except Exception:
                    continue
                if "<packaging>maven-plugin</packaging>" in content:
                    logger.debug("Installing Maven plugin module: %s",
                                pom_path.parent.relative_to(compile_dir))
                    subprocess.run(
                        [mvn, "install", "-f", str(pom_path)] + skip_flags,
                        cwd=compile_dir, capture_output=True, text=True,
                        timeout=180, env=env,
                    )
        except Exception as e:
            logger.debug("Error scanning for Maven plugins: %s", e)

    def compile_project(self, repo_dir: Path, commit: Optional[Dict] = None) -> Tuple[bool, Optional[str]]:
        """Compile the project using Apache Maven. Targets specific module if file info available."""
        root_pom = self._find_root_pom(repo_dir)
        if not root_pom:
            logger.error("No pom.xml found")
            return False, None

        compile_dir = root_pom.parent
        env = os.environ.copy()
        if self.java_home != Path("/usr"):
            env["JAVA_HOME"] = str(self.java_home.resolve())
            env["PATH"] = str(self.java_home / "bin") + ":" + env.get("PATH", "")
            logger.debug("Set JAVA_HOME=%s", env["JAVA_HOME"])
        mvn = self.maven_cmd

        target_module = None
        if commit:
            target_module = self._extract_module_from_files(commit)

        skip_flags = [
            "-DskipTests", "-Dmaven.test.skip=true",
            "-Dmaven.javadoc.skip=true", "-Dcheckstyle.skip=true",
            "-Denforcer.skip=true", "-Drat.skip=true",
            "-Dpmd.skip=true", "-Dspotbugs.skip=true",
            "-Dfindbugs.skip=true", "-Danimal.sniffer.skip=true",
            "-fn", "-B", "-U",
        ]

        try:
            logger.debug("Installing root POM...")
            subprocess.run(
                [mvn, "install", "-N"] + skip_flags,
                cwd=compile_dir, capture_output=True, text=True,
                timeout=120, env=env,
            )

            if target_module:
                for tooling in ["tooling", "buildtools", "build-tools", "parent",
                                "tooling/maven", "build"]:
                    tooling_pom = compile_dir / tooling / "pom.xml"
                    if tooling_pom.exists():
                        logger.debug("Pre-installing build tooling: %s", tooling)
                        subprocess.run(
                            [mvn, "install", "-N", "-f", str(tooling_pom)] + skip_flags,
                            cwd=compile_dir, capture_output=True, text=True,
                            timeout=120, env=env,
                        )
                        subprocess.run(
                            [mvn, "install", "-f", str(tooling_pom)] + skip_flags,
                            cwd=compile_dir, capture_output=True, text=True,
                            timeout=300, env=env,
                        )

                self._install_maven_plugins(compile_dir, mvn, skip_flags, env)

            maven_goal = "install" if target_module else "compile"
            maven_flags = [mvn, maven_goal] + skip_flags
            
            if target_module:
                module_pom = compile_dir / target_module / "pom.xml"
                if module_pom.exists():
                    maven_flags.extend(["-pl", target_module, "-am"])
                    logger.debug("Installing specific module: %s (with dependencies)", target_module)
                else:
                    logger.warning("Module pom.xml not found at %s, compiling entire project", module_pom)
            else:
                logger.debug("No specific module detected, compiling entire project...")
            
            result = subprocess.run(
                maven_flags,
                cwd=compile_dir, capture_output=True, text=True,
                timeout=600, env=env,
            )

            search_dir = (compile_dir / target_module) if target_module else compile_dir
            classes_dirs = list(search_dir.glob("**/target/classes"))

            if not classes_dirs and target_module:
                logger.warning("Module-specific compilation produced no classes, trying full project...")
                fallback_flags = [mvn, "install"] + skip_flags
                result = subprocess.run(
                    fallback_flags,
                    cwd=compile_dir, capture_output=True, text=True,
                    timeout=600, env=env,
                )
                classes_dirs = list(search_dir.glob("**/target/classes"))
            
            if not classes_dirs:
                logger.error("No target/classes directories found after compilation")
                stdout_lines = result.stdout.strip().split("\n")
                error_lines = [l for l in stdout_lines if "ERROR" in l or "FATAL" in l]
                if error_lines:
                    logger.error("Maven errors: %s", "\n".join(error_lines[:10]))
                logger.error("Maven exit code: %d", result.returncode)
                return False, None

            logger.debug("Compiled successfully, found %d target/classes directories", len(classes_dirs))

            cp_dir = (compile_dir / target_module) if target_module else compile_dir
            cp_pom = cp_dir / "pom.xml"
            
            if cp_pom.exists():
                result = subprocess.run(
                    [mvn, "dependency:build-classpath", "-DincludeScope=compile",
                     "-Dmdep.outputFile=/dev/stdout", "-q",
                     "-f", str(cp_pom.resolve()), "-B"],
                    cwd=str(compile_dir), capture_output=True, text=True,
                    timeout=180, env=env,
                )
                if result.returncode == 0 and result.stdout.strip():
                    dep_cp = result.stdout.strip()
                    cp_parts = [str(d) for d in classes_dirs]
                    if dep_cp:
                        cp_parts.append(dep_cp)
                    return True, ":".join(cp_parts)

            classpath = ":".join(str(d) for d in classes_dirs)
            logger.warning("Using fallback classpath: %d target/classes dirs only", len(classes_dirs))
            return True, classpath

        except subprocess.TimeoutExpired:
            logger.error("Maven compilation timeout")
            return False, None
        except Exception as e:
            logger.error("Compilation error: %s", e)
            return False, None

    def collect_compiled_classes(self, repo_dir: Path) -> List[str]:
        """Collect all compiled class names from the project."""
        classes = []
        classes_dirs = list(repo_dir.glob("**/target/classes"))
        if not classes_dirs:
            logger.warning("No target/classes directories found in %s", repo_dir)
            return []

        logger.debug("Scanning %d target/classes directories", len(classes_dirs))
        for classes_dir in classes_dirs:
            for class_file in classes_dir.rglob("*.class"):
                try:
                    rel = str(class_file.relative_to(classes_dir))
                    class_name = rel[:-6].replace("/", ".")
                    if "$" in class_name or "Test" in class_name:
                        continue
                    classes.append(class_name)
                except Exception as e:
                    logger.debug("Error processing class file %s: %s", class_file, e)

        logger.debug("Found %d compiled classes across all modules", len(classes))
        return classes

    def generate_tests_randoop(self, project: str, sha: str, classpath: str,
                               classes: List[str], out_dir: Path) -> int:
        """Generate tests with Randoop against compiled classes."""
        if not self.randoop_jar.exists():
            logger.warning("Randoop JAR not found")
            return 0

        java = str(self.java_home / "bin" / "java")

        try:
            logger.debug("Generating tests with Randoop (time limit: 60s)...")
            class_list = classes[:50]

            classlist_file = out_dir / "classlist.txt"
            classlist_file.write_text("\n".join(class_list))

            full_cp = f"{self.randoop_jar}:{classpath}"

            result = subprocess.run(
                [java, "-cp", full_cp, "randoop.main.Main",
                 "gentests",
                 f"--classlist={classlist_file}",
                 f"--time-limit=60",
                 f"--junit-output-dir={out_dir}"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                if result.stderr:
                    logger.warning("Randoop stderr: %s", result.stderr[:300])
                if result.stdout:
                    logger.debug("Randoop stdout (last 300): %s", result.stdout[-300:])

            test_files = [f for f in out_dir.glob("**/*.java")
                          if f.name != "classlist.txt"]
            if test_files:
                logger.debug("Randoop generated %d test files", len(test_files))
                return len(test_files)
            else:
                logger.warning("Randoop produced no test files")

        except subprocess.TimeoutExpired:
            logger.warning("Randoop timeout")
        except Exception as e:
            logger.error("Randoop generation error: %s", e)

        return 0

    def _extract_target_classes(self, commit: Dict) -> List[str]:
        """Extract fully-qualified class names from the commit's file paths."""
        classes = []
        files = commit.get("files", [])
        for f in files:
            fname = f.get("file_name", "")
            marker = "src/main/java/"
            idx = fname.find(marker)
            if idx >= 0 and fname.endswith(".java"):
                rel = fname[idx + len(marker):]
                class_name = rel[:-5].replace("/", ".")
                classes.append(class_name)
        return classes

    def generate_for_commit(self, commit: Dict) -> Dict:
        """Generate tests for a single commit using Randoop."""
        project, sha = commit["project"], commit["commit_sha"]
        result = {
            "project": project,
            "commit_sha": sha,
            "tests_generated": 0,
            "tool": "randoop",
            "status": "failed"
        }

        repo = self.clone_and_checkout(project, sha)
        if not repo:
            logger.error("Failed to clone repository")
            self.stats["failures"] += 1
            return result
        self.stats["commits_cloned"] += 1

        success, classpath = self.compile_project(repo, commit)
        if not success or not classpath:
            logger.error("Failed to compile project")
            self.stats["failures"] += 1
            return result
        self.stats["commits_compiled"] += 1

        target_classes = self._extract_target_classes(commit)
        if target_classes:
            logger.debug("Targeting %d specific classes from commit: %s",
                        len(target_classes), ", ".join(target_classes))
            classes = target_classes
        else:
            classes = self.collect_compiled_classes(repo)
            if not classes:
                logger.error("No compiled classes found")
                self.stats["failures"] += 1
                return result

        out_dir = self.output_dir / f"{project}_{sha[:8]}_tests"
        out_dir.mkdir(exist_ok=True)

        tests_generated = self.generate_tests_randoop(project, sha, classpath, classes, out_dir)

        if tests_generated > 0:
            result["tests_generated"] = tests_generated
            result["status"] = "success"
            self.stats["tests_generated"] += tests_generated
        else:
            result["status"] = "no_tests"

        return result

    def process_commits(self, commits: List[Dict]) -> Dict:
        logger.info("=" * 70)
        logger.info("TIER 3b: RANDOOP TEST GENERATION (FALLBACK)")
        logger.info("=" * 70)
        logger.info("Commits to process: %d", len(commits))

        results = []
        for idx, c in enumerate(commits, 1):
            self.stats["commits_attempted"] += 1
            logger.info(
                "[%d/%d] %s/%s", idx, len(commits),
                c["project"], c["commit_sha"][:8],
            )
            r = self.generate_for_commit(c)
            results.append(r)

        (self.output_dir / "randoop_results.json").write_text(
            json.dumps({"stats": self.stats, "results": results}, indent=2)
        )

        logger.info("-" * 70)
        logger.info("Tier 3b Randoop fallback results:")
        logger.info("  Attempted : %d", self.stats["commits_attempted"])
        logger.info("  Cloned    : %d", self.stats["commits_cloned"])
        logger.info("  Compiled  : %d", self.stats["commits_compiled"])
        logger.info("  Generated : %d", self.stats["tests_generated"])
        logger.info("  Failures  : %d", self.stats["failures"])
        logger.info("-" * 70)

        return {"tier": "3b", "stats": self.stats, "results": results}


# ---------------------------------------------------------------------------
# Tier 4: LLM-based test generation (placeholder / future)
# ---------------------------------------------------------------------------

class LLMTestGenerator:
    """Generate tests using an LLM (e.g. Claude) for remaining gaps."""

    def __init__(self, output_dir: str = "tier4_llm"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.stats = {"attempted": 0, "generated": 0}

    def generate_for_file(self, project: str, sha: str, fpath: str, content: str) -> Optional[Dict]:
        """
        Placeholder: call an LLM API to generate unit tests for *content*.
        Override or extend this with actual API calls.
        """
        # TODO: integrate Anthropic / OpenAI API here
        return None

    def process_commits(self, commits: List[Dict]) -> Dict:
        logger.info("=" * 70)
        logger.info("TIER 4: LLM TEST GENERATION (placeholder)")
        logger.info("=" * 70)
        logger.info("Commits available: %d", len(commits))
        logger.info("(Not yet implemented – extend LLMTestGenerator.generate_for_file)")
        return {"tier": 4, "stats": self.stats}
