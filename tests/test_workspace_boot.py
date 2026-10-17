"""A slow package integrity check must not stall unrelated workspace requests."""
import asyncio
import threading

import httpx

from geo_harness.app import create_app


def test_session_and_map_context_remain_available_while_catalogue_is_verified(tmp_path, monkeypatch):
    app = create_app(tmp_path, _principal='member')
    products = app.state.products
    original = products.catalog
    started, release = threading.Event(), threading.Event()

    def slow_catalogue():
        started.set()
        assert release.wait(5), 'catalogue blocked the request event loop'
        return original()

    monkeypatch.setattr(products, 'catalog', slow_catalogue)

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            assert (await client.get('/')).status_code == 200
            pending = asyncio.create_task(client.get('/api/bootstrap'))
            try:
                assert await asyncio.to_thread(started.wait, 3)
                session = await asyncio.wait_for(client.get('/api/session'), 2)
                context = await asyncio.wait_for(client.get('/api/workbench/context'), 2)
                assert session.status_code == context.status_code == 200
                assert session.json()['account']['principal'] == 'member'
                assert session.json()['version']
                assert session.json()['platform_url']
                assert not pending.done()
            finally:
                release.set()
                response = await pending
            assert response.status_code == 200
            assert response.json()['catalog']
    asyncio.run(check())
