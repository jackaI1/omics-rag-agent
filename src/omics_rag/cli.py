import argparse
import json
import sys
from pathlib import Path

from .agents import QA


def main():
    parser = argparse.ArgumentParser(
        description="Cited questions over a public normal-tissue RNA extract"
    )
    parser.add_argument("question", nargs="?")
    parser.add_argument(
        "--model", default="mock", help="mock (offline) or an installed Ollama tool-calling model"
    )
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--force-agents", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--topic-agent", action="store_true", help="Route through configured topics"
    )
    parser.add_argument(
        "--usage-log", type=Path, help="Append question and per-stage usage JSON locally"
    )
    parser.add_argument("--catalog", action="store_true")
    parser.add_argument(
        "--search", action="store_true", help="Rank individual measurement descriptions"
    )
    parser.add_argument("--retrieval", choices=["tfidf", "embedding", "hybrid"], default="tfidf")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--evaluate-retrieval", action="store_true")
    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Run 30 checked-in evaluation questions with chosen model",
    )
    args = parser.parse_args()
    model = None
    if args.model != "mock":
        from langchain_ollama import ChatOllama

        model = ChatOllama(
            model=args.model,
            base_url=args.base_url,
            temperature=0,
            num_ctx=16384,
            num_predict=1024,
            keep_alive=0,
            reasoning=False,
        )
    try:
        with QA(model, retrieval=args.retrieval) as qa:
            if args.evaluate_retrieval:
                from .retrieval_evaluation import evaluate

                print(json.dumps(evaluate(qa.store, args.k), indent=2))
                return
            if args.search:
                if not args.question:
                    parser.error("--search needs a question")
                print(
                    json.dumps(
                        qa.store.search_measurements(args.question, mode=args.retrieval, k=args.k),
                        indent=2,
                    )
                )
                return
            if args.catalog:
                print(
                    json.dumps(
                        {
                            "genes": qa.store.genes,
                            "tissues": qa.store.tissues,
                            "sources": qa.store.sources,
                        },
                        indent=2,
                    )
                )
                return
            if args.evaluate:
                from .evaluation import evaluate

                result = evaluate(qa)
                print(json.dumps(result, indent=2))
                if result["passed"] != result["total"]:
                    sys.exit(1)
                return
            if not args.question:
                parser.error("provide a question, --catalog or --evaluate")
            if args.topic_agent:
                import logging

                from .topic_agent import TopicAgent

                logging.basicConfig(level=logging.INFO)
                result = TopicAgent(qa).ask(args.question)
                print(json.dumps(result, indent=2) if args.json else result["answer"])
                return
            result = qa.ask(args.question, force_agents=args.force_agents)
            if args.usage_log:
                with args.usage_log.open("a") as handle:
                    handle.write(
                        json.dumps(
                            {
                                k: result[k]
                                for k in ["question", "route", "model", "usage", "total_tokens"]
                            }
                        )
                        + "\n"
                    )
            print(
                json.dumps(result, indent=2)
                if args.json
                else result["answer"]
                + f"\nRoute: {result['route']}; tokens: {result['total_tokens']}"
            )
    except Exception as error:
        print(f"No answer emitted: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
