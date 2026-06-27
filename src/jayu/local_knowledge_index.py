from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .paths import RuntimePaths


class LocalKnowledgeIndex:
    """Lightweight local RAG indexing and search engine for Jayu.
    
    Indexes project documentation (README, docs) and runtime artifacts (signals, runs).
    """

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        self.paths = RuntimePaths.from_root(self.project_root)
        self.documents: list[dict[str, Any]] = []

    def build_index(self) -> int:
        """Scan and index all documentation and runtime artifacts.
        
        Returns the number of indexed documents.
        """
        self.documents.clear()

        # 1. Index README.md
        readme_path = self.project_root / "README.md"
        if readme_path.exists():
            try:
                content = readme_path.read_text(encoding="utf-8")
                self.documents.append({
                    "path": str(readme_path.relative_to(self.project_root)),
                    "title": "프로젝트 README",
                    "type": "documentation",
                    "content": content,
                })
            except Exception:
                pass

        # 2. Index docs/ directory if it exists
        docs_dir = self.project_root / "docs"
        if docs_dir.exists() and docs_dir.is_dir():
            for root, _, files in os.walk(docs_dir):
                for file in files:
                    if file.endswith((".md", ".txt")):
                        file_path = Path(root) / file
                        try:
                            content = file_path.read_text(encoding="utf-8")
                            self.documents.append({
                                "path": str(file_path.relative_to(self.project_root)),
                                "title": f"문서: {file_path.name}",
                                "type": "documentation",
                                "content": content,
                            })
                        except Exception:
                            pass

        # 3. Index signals/ directory
        signals_dir = self.paths.signals_dir
        if signals_dir.exists():
            for root, _, files in os.walk(signals_dir):
                for file in files:
                    if file.endswith(".json"):
                        file_path = Path(root) / file
                        try:
                            data = json.loads(file_path.read_text(encoding="utf-8"))
                            pretty_json = json.dumps(data, indent=2, ensure_ascii=False)
                            self.documents.append({
                                "path": str(file_path.relative_to(self.project_root)),
                                "title": f"신호 데이터: {file_path.name}",
                                "type": "signal",
                                "content": pretty_json,
                                "raw_data": data,
                            })
                        except Exception:
                            pass

        # 4. Index runs/ directory (latest runs first or limit to prevent massive index)
        runs_dir = self.paths.runs_dir
        if runs_dir.exists():
            # Get all run subdirectories, sort by name descending (latest first)
            run_paths = sorted([d for d in runs_dir.iterdir() if d.is_dir()], key=lambda x: x.name, reverse=True)
            # Index up to 10 latest runs to keep performance high
            for run_path in run_paths[:10]:
                for root, _, files in os.walk(run_path):
                    for file in files:
                        if file.endswith((".json", ".md", ".txt")):
                            file_path = Path(root) / file
                            try:
                                content = file_path.read_text(encoding="utf-8")
                                if file.endswith(".json"):
                                    data = json.loads(content)
                                    content = json.dumps(data, indent=2, ensure_ascii=False)
                                else:
                                    data = None
                                self.documents.append({
                                    "path": str(file_path.relative_to(self.project_root)),
                                    "title": f"실행[{run_path.name}] {file_path.name}",
                                    "type": "run_artifact",
                                    "content": content,
                                    "raw_data": data,
                                })
                            except Exception:
                                pass

        return len(self.documents)

    def search(self, query: str, top_n: int = 3) -> list[dict[str, Any]]:
        """Search the indexed documents using a term frequency overlapping scorer."""
        if not self.documents:
            self.build_index()

        query_terms = [term.lower().strip() for term in query.split() if len(term.strip()) > 0]
        if not query_terms:
            return []

        scored_docs = []
        for doc in self.documents:
            score = 0.0
            content_lower = doc["content"].lower()
            title_lower = doc["title"].lower()
            path_lower = doc["path"].lower()

            for term in query_terms:
                # Term matches in path (highest weight)
                if term in path_lower:
                    score += 10.0
                # Term matches in title (high weight)
                if term in title_lower:
                    score += 5.0
                # Term matches in body
                term_count = content_lower.count(term)
                if term_count > 0:
                    # Logarithmic scaling for term frequency to prevent single document flooding
                    score += 1.0 + math.log(term_count)

            if score > 0:
                scored_docs.append((score, doc))

        # Sort by score descending
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored_docs[:top_n]]

    def ask_jayu(self, query: str) -> dict[str, Any]:
        """Perform a grounded query (RAG) and generate a natural Korean response."""
        results = self.search(query, top_n=3)
        
        if not results:
            return {
                "query": query,
                "answer": "죄송합니다. 관련 문서를 찾지 못했습니다. 질문에 포함된 키워드(예: 종목 코드, 리스크, 신호, 백테스트 등)를 더 구체적으로 입력해 주세요.",
                "sources": [],
            }

        # Build answer based on retrieved artifacts
        sources_list = [r["path"] for r in results]
        
        # Simple rule-based/template-based synthesizer
        # If we have a specific signal, risk, or doc, extract and format nicely.
        answer_parts = []
        for doc in results:
            doc_type = doc["type"]
            path_name = doc["path"]
            
            if doc_type == "signal":
                raw = doc.get("raw_data", {})
                answer_parts.append(
                    f"### 📊 신호 데이터 분석 ({path_name})\n"
                    f"최근 생성된 신호 데이터에서 다음과 같은 항목이 발견되었습니다:\n"
                    f"```json\n{json.dumps(raw, indent=2, ensure_ascii=False)[:300]}...\n```"
                )
            elif doc_type == "run_artifact":
                raw = doc.get("raw_data", {})
                status_str = ""
                if isinstance(raw, dict):
                    status_str = f" - 상태: {raw.get('status', 'N/A')}"
                answer_parts.append(
                    f"### ⚙️ 실행 산출물 분석 ({path_name}){status_str}\n"
                    f"실행 증거 파일에서 추출한 내용입니다:\n"
                    f"```json\n{json.dumps(raw, indent=2, ensure_ascii=False)[:300]}...\n```"
                )
            elif doc_type == "documentation":
                # Extract a snippet around query terms
                body = doc["content"]
                snippet = body[:400] + ("..." if len(body) > 400 else "")
                answer_parts.append(
                    f"### 📖 문서 내용 참조 ({path_name})\n"
                    f"운영 가이드 또는 설계 문서의 일부 내용입니다:\n"
                    f"```markdown\n{snippet}\n```"
                )

        answer_intro = f"**질문 '{query}'에 대해 색인된 {len(results)}개의 프로젝트 문서를 기반으로 분석한 결과입니다.**\n\n"
        full_answer = answer_intro + "\n\n".join(answer_parts)

        return {
            "query": query,
            "answer": full_answer,
            "sources": sources_list,
        }
