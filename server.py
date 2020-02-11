import asyncio
from signal import SIGINT, signal

from sanic import Sanic, response

from MaterialPlanning import MaterialPlanning

app = Sanic(name="ArkPlanner")
mp = MaterialPlanning()
mp.update()


@app.route("/plan", methods=["POST"])
async def plan(request):
    try:
        input_data = request.json
        owned_dct = input_data["owned"]
        required_dct = input_data["required"]
    except:
        return response.json({"error": True, "reason": "Uninterpretable input"})

    try:
        extra_outc = request.json["extra_outc"]
    except:
        extra_outc = False

    try:
        exp_demand = request.json["exp_demand"]
    except:
        exp_demand = True

    try:
        gold_demand = request.json["gold_demand"]
    except:
        gold_demand = True

    try:
        dct = mp.get_plan(
            required_dct,
            owned_dct,
            False,
            outcome=extra_outc,
            exp_demand=exp_demand,
            gold_demand=gold_demand,
        )
    except ValueError as e:
        return response.json({"error": True, "reason": str(e)})

    return response.json(dct)


async def update_coro():
    while True:
        # Sleep an hour before checking for updates
        await asyncio.sleep(60 * 60)
        mp.update()


def main():
    serv_coro = app.create_server(host="localhost", port=8000, return_asyncio_server=True)
    loop = asyncio.get_event_loop()
    signal(SIGINT, lambda s, f: loop.stop())
    serv_task = asyncio.ensure_future(serv_coro, loop=loop)
    loop.run_until_complete(serv_task)
    asyncio.Task(update_coro(), loop=loop)  # type: ignore
    try:
        loop.run_forever()
    except:
        loop.stop()


if __name__ == "__main__":
    try:
        import uvloop

        asyncio.set_event_loop(uvloop.new_event_loop())
        print("Using uvloop")
    except:
        print("Using asyncio loop")
    main()
