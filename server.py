import asyncio
from signal import SIGINT, signal

from marshmallow import Schema, fields, validate
from marshmallow.exceptions import ValidationError
from sanic import Sanic, response

from MaterialPlanning import MaterialPlanning

app = Sanic(name="ArkPlanner")
mp = MaterialPlanning()
region_lang_map = {
    "en": "en_US",
    "jp": "ja_JP",
    "kr": "ko_KR",
    "cn": "zh_CN",
    "id": "id",
}


class PlanSchema(Schema):
    # Output language, will match requirement language if not specified.
    out_lang = fields.Str(validate=validate.OneOf(["en", "cn", "jp", "kr", "id"]))
    # Consider crafting byproducts
    extra_outc = fields.Bool(missing=False)
    # Compatibility mode for non Chinese servers (EN/JP/KR) to only consider
    # content that is available to them.
    non_cn_compat = fields.Bool(missing=False)
    exclude = fields.List(fields.Str(), missing=None)
    exp_demand = fields.Bool(missing=False)
    gold_demand = fields.Bool(missing=True)
    # A map of an item's name (in either of the 4 languages) or its ID,
    # to a number representing the quantity desired.
    required = fields.Dict(
        keys=fields.String(),
        values=fields.Integer(),
        required=True,
        validate=validate.Length(min=1),
    )
    # Items already in a user's possession.
    owned = fields.Dict(keys=fields.String(), values=fields.Integer(), missing=None)


schema = PlanSchema()


@app.route("/plan", methods=["POST"])
async def plan(request):
    try:
        request = schema.load(request.json)
    except ValidationError as e:
        return response.json({"error": {"request_validation_error": e.messages}})

    if request["owned"] is None:
        request["owned"] = {}

    try:
        dct = mp.get_plan(
            request["required"],
            request["owned"],
            False,
            outcome=request["extra_outc"],
            exp_demand=request["exp_demand"],
            gold_demand=request["gold_demand"],
            language=region_lang_map[request["out_lang"]],
            non_cn_compat=request["non_cn_compat"],
            exclude=request["exclude"],
        )
    except ValueError as e:
        return response.json({"error": True, "reason": str(e)})

    return response.json(dct)


async def update_coro():
    while True:
        # Sleep an hour before checking for updates
        await asyncio.sleep(60 * 60)
        mp.update()


if __name__ == "__main__":
    try:
        import uvloop  # type: ignore

        asyncio.set_event_loop(uvloop.new_event_loop())
    except ImportError:
        # Allow development on Windows
        pass

    serv_coro = app.create_server(port=8000, return_asyncio_server=True)

    loop = asyncio.get_event_loop()
    signal(SIGINT, lambda s, f: loop.stop())
    serv_task = asyncio.ensure_future(serv_coro, loop=loop)
    loop.run_until_complete(serv_task)
    asyncio.Task(update_coro(), loop=loop)  # type: ignore
    try:
        loop.run_forever()
    except BaseException:
        loop.stop()
