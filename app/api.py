from flask import Blueprint, Response, current_app, jsonify, request

from app.business import DomainIssue
from app.evidence.render import artifact
from app.inputs import read_input
from app.modules.pipeline import run
from app.modules.release import decorate
from app.review.service import execute, present, review

api = Blueprint("api", __name__, url_prefix="/api")
STAGES = {"intake": 1, "prepare": 2, "calculate": 3, "policy": 4, "balance": 5}


@api.post("/stages/<stage>")
def preview(stage):
    if stage not in STAGES:
        raise DomainIssue("STAGE_UNKNOWN")
    store = current_app.extensions["runs"]
    output = run(read_input(), STAGES[stage])
    # 采信与同步点校核阶段还没有读数，不必套用签发出的冻结值。
    if STAGES[stage] >= 3:
        output = decorate(output, store.previous(), store.issued())
    return jsonify(output)


@api.route("/runs", methods=["GET", "POST"])
def runs():
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(items=store.list())
    return jsonify(execute(store, read_input()))


@api.route("/runs/<run_id>", methods=["GET", "PATCH"])
def batch(run_id):
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(present(store, run_id))
    return jsonify(review(store, run_id, request.get_json(silent=True)))


@api.get("/releases")
def releases():
    store = current_app.extensions["runs"]
    return jsonify(items=store.releases(), active=store.active())


@api.get("/runs/<run_id>/evidence")
def export(run_id):
    report = present(current_app.extensions["runs"], run_id)
    return Response(
        artifact(report),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="review-{report["id"][:12]}.json"',
            "Cache-Control": "no-store",
        },
    )
