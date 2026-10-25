# Extension guide

Specifications will change. These are the supported seams.

## Add or swap an adapter (sponsor API, database)
1. Find the port in `ports/__init__.py`.
2. Write a contract test that any implementation must pass (reuse the in-memory adapter's tests by parametrizing the fixture).
3. Implement `adapters/<name>.py`. Import vendor SDKs lazily and fall back to the in-memory adapter on failure.
4. Register it in `container.py` behind a `Settings` flag. Nothing else changes.

## Change dispatch behaviour
Implement `DispatchPolicy.decide` in a new class (for example `FleetPolicy` for multi-robot) and pass it to `Dispatcher` in `container.py`. Do not edit `Dispatcher`.

## Add an alert channel
Implement `Notifier.send`, wrap with `CompositeNotifier` in the container. Channels are independent; one failing never blocks another.

## React to something that happens
Subscribe a handler to a domain event on the `EventBus` (new service class with a `register()`/constructor subscription). Handlers must be idempotent. To add a new event, add a frozen dataclass to `domain/events.py` and publish it from the owning service.

## Add a field to a model
Add it with a default (so stored data and the API stay compatible), add a test, update the API schema tests and the module map.

## Add an endpoint
Routes live in `api/app.py`, call exactly one service method, and contain no rules. Add an API test with `httpx`/`TestClient`.
