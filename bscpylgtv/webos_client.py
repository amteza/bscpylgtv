import asyncio
import base64
import copy
import functools
import json
import logging
import os
from datetime import timedelta

import websockets
from sqlitedict import SqliteDict

from . import buttons as btn
from . import endpoints as ep
from .handshake import REGISTRATION_MESSAGE

logger = logging.getLogger(__name__)


KEY_FILE_NAME = ".aiopylgtv.sqlite"
USER_HOME = "HOME"

SOUND_OUTPUTS_TO_DELAY_CONSECUTIVE_VOLUME_STEPS = {"external_arc"}


class PyLGTVPairException(Exception):
    def __init__(self, message):
        self.message = message


class PyLGTVCmdException(Exception):
    def __init__(self, message):
        self.message = message


class PyLGTVCmdError(PyLGTVCmdException):
    def __init__(self, message):
        self.message = message


class PyLGTVServiceNotFoundError(PyLGTVCmdError):
    def __init__(self, message):
        self.message = message


class WebOsClient:
    def __init__(
        self,
        ip,
        key_file_path=None,
        timeout_connect=2,
        ping_interval=1,
        ping_timeout=20,
        client_key=None,
        volume_step_delay_ms=None,
    ):
        """Initialize the client."""
        self.ip = ip
        self.port = 3000
        self.key_file_path = key_file_path
        self.client_key = client_key
        self.web_socket = None
        self.command_count = 0
        self.timeout_connect = timeout_connect
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.connect_task = None
        self.connect_result = None
        self.connection = None
        self.input_connection = None
        self.callbacks = {}
        self.futures = {}
        self._power_state = {}
        self._current_appId = None
        self._muted = None
        self._volume = None
        self._current_channel = None
        self._channel_info = None
        self._channels = None
        self._apps = {}
        self._extinputs = {}
        self._system_info = None
        self._software_info = None
        self._sound_output = None
        self._picture_settings = None
        self.state_update_callbacks = []
        self.doStateUpdate = False
        self._volume_step_lock = asyncio.Lock()
        self._volume_step_delay = (
            timedelta(milliseconds=volume_step_delay_ms)
            if volume_step_delay_ms is not None
            else None
        )

    @classmethod
    async def create(cls, *args, **kwargs):
        client = cls(*args, **kwargs)
        await client.async_init()
        return client

    async def async_init(self):
        """Load client key from config file if in use."""
        if self.client_key is None:
            self.client_key = await asyncio.get_running_loop().run_in_executor(
                None, self.read_client_key
            )

    @staticmethod
    def _get_key_file_path():
        """Return the key file path."""
        if os.getenv(USER_HOME) is not None and os.access(
            os.getenv(USER_HOME), os.W_OK
        ):
            return os.path.join(os.getenv(USER_HOME), KEY_FILE_NAME)

        return os.path.join(os.getcwd(), KEY_FILE_NAME)

    def read_client_key(self):
        """Try to load the client key for the current ip."""

        if self.key_file_path:
            key_file_path = self.key_file_path
        else:
            key_file_path = self._get_key_file_path()

        logger.debug("load keyfile from %s", key_file_path)

        with SqliteDict(key_file_path) as conf:
            return conf.get(self.ip)

    def write_client_key(self):
        """Save the current client key."""
        if self.client_key is None:
            return

        if self.key_file_path:
            key_file_path = self.key_file_path
        else:
            key_file_path = self._get_key_file_path()

        logger.debug("save keyfile to %s", key_file_path)

        with SqliteDict(key_file_path) as conf:
            conf[self.ip] = self.client_key
            conf.commit()

    async def connect(self):
        if not self.is_connected():
            self.connect_result = asyncio.Future()
            self.connect_task = asyncio.create_task(
                self.connect_handler(self.connect_result)
            )
        return await self.connect_result

    async def disconnect(self):
        if self.is_connected():
            self.connect_task.cancel()
            try:
                await self.connect_task
            except asyncio.CancelledError:
                pass

    def is_registered(self):
        """Paired with the tv."""
        return self.client_key is not None

    def is_connected(self):
        return self.connect_task is not None and not self.connect_task.done()

    def registration_msg(self):
        handshake = copy.deepcopy(REGISTRATION_MESSAGE)
        handshake["payload"]["client-key"] = self.client_key
        return handshake

    async def connect_handler(self, res):

        handler_tasks = set()
        ws = None
        try:
            ws = await asyncio.wait_for(
                websockets.connect(
                    f"ws://{self.ip}:{self.port}",
                    ping_interval=None,
                    close_timeout=self.timeout_connect,
                    max_size=None,
                ),
                timeout=self.timeout_connect,
            )
            await ws.send(json.dumps(self.registration_msg()))
            raw_response = await ws.recv()
            response = json.loads(raw_response)

            if (
                response["type"] == "response"
                and response["payload"]["pairingType"] == "PROMPT"
            ):
                raw_response = await ws.recv()
                response = json.loads(raw_response)
                if response["type"] == "registered":
                    self.client_key = response["payload"]["client-key"]
                    await asyncio.get_running_loop().run_in_executor(
                        None, self.write_client_key
                    )

            if not self.client_key:
                raise PyLGTVPairException("Unable to pair")

            self.callbacks = {}
            self.futures = {}

            handler_tasks.add(
                asyncio.create_task(
                    self.consumer_handler(ws, self.callbacks, self.futures)
                )
            )
            if self.ping_interval is not None:
                handler_tasks.add(
                    asyncio.create_task(
                        self.ping_handler(ws, self.ping_interval, self.ping_timeout)
                    )
                )
            self.connection = ws

            # set static state and subscribe to state updates
            # avoid partial updates during initial subscription

            self.doStateUpdate = False
            #chros self._system_info, self._software_info = await asyncio.gather(
            #chros     self.get_system_info(), self.get_software_info()
            #chros )
            subscribe_coros = {
                #chros self.subscribe_power_state(self.set_power_state),
                #chros self.subscribe_current_app(self.set_current_app_state),
                #chros self.subscribe_muted(self.set_muted_state),
                #chros self.subscribe_volume(self.set_volume_state),
                #chros self.subscribe_apps(self.set_apps_state),
                #chros self.subscribe_inputs(self.set_inputs_state),
                #chros self.subscribe_sound_output(self.set_sound_output_state),
                #chros self.subscribe_picture_settings(self.set_picture_settings_state),
            }
            subscribe_tasks = set()
            if subscribe_coros:
                for coro in subscribe_coros:
                    subscribe_tasks.add(asyncio.create_task(coro))
                await asyncio.wait(subscribe_tasks)
                for task in subscribe_tasks:
                    try:
                        task.result()
                    except PyLGTVServiceNotFoundError:
                        pass
            # set placeholder power state if not available
            if not self._power_state:
                self._power_state = {"state": "Unknown"}
            self.doStateUpdate = True
            if self.state_update_callbacks:
                await self.do_state_update_callbacks()

            res.set_result(True)

            await asyncio.wait(handler_tasks, return_when=asyncio.FIRST_COMPLETED)

        except Exception as ex:
            if not res.done():
                res.set_exception(ex)
        finally:
            for task in handler_tasks:
                if not task.done():
                    task.cancel()

            for future in self.futures.values():
                future.cancel()

            closeout = set()
            closeout.update(handler_tasks)

            if ws is not None:
                closeout.add(asyncio.create_task(ws.close()))
            if self.input_connection is not None:
                closeout.add(asyncio.create_task(self.input_connection.close()))

            self.connection = None
            self.input_connection = None

            self.doStateUpdate = False

            self._power_state = {}
            self._current_appId = None
            self._muted = None
            self._volume = None
            self._current_channel = None
            self._channel_info = None
            self._channels = None
            self._apps = {}
            self._extinputs = {}
            self._system_info = None
            self._software_info = None
            self._sound_output = None
            self._picture_settings = None

            for callback in self.state_update_callbacks:
                closeout.add(callback())

            if closeout:
                closeout_task = asyncio.create_task(asyncio.wait(closeout))

                while not closeout_task.done():
                    try:
                        await asyncio.shield(closeout_task)
                    except asyncio.CancelledError:
                        pass

    async def ping_handler(self, ws, interval, timeout):
        try:
            while True:
                await asyncio.sleep(interval)
                # In the "Suspend" state the tv can keep a connection alive, but will not respond to pings
                if self._power_state.get("state") != "Suspend":
                    ping_waiter = await ws.ping()
                    if timeout is not None:
                        await asyncio.wait_for(ping_waiter, timeout=timeout)
        except (
            asyncio.TimeoutError,
            asyncio.CancelledError,
            websockets.exceptions.ConnectionClosedError,
        ):
            pass

    async def callback_handler(self, queue, callback, future):
        try:
            while True:
                msg = await queue.get()
                payload = msg.get("payload")
                await callback(payload)
                if future is not None and not future.done():
                    future.set_result(msg)
        except asyncio.CancelledError:
            pass

    async def consumer_handler(self, ws, callbacks={}, futures={}):

        callback_queues = {}
        callback_tasks = {}

        try:
            async for raw_msg in ws:
                if callbacks or futures:
                    msg = json.loads(raw_msg)
                    uid = msg.get("id")
                    callback = self.callbacks.get(uid)
                    future = self.futures.get(uid)
                    if callback is not None:
                        if uid not in callback_tasks:
                            queue = asyncio.Queue()
                            callback_queues[uid] = queue
                            callback_tasks[uid] = asyncio.create_task(
                                self.callback_handler(queue, callback, future)
                            )
                        callback_queues[uid].put_nowait(msg)
                    elif future is not None and not future.done():
                        self.futures[uid].set_result(msg)

        except (websockets.exceptions.ConnectionClosedError, asyncio.CancelledError):
            pass
        finally:
            for task in callback_tasks.values():
                if not task.done():
                    task.cancel()

            tasks = set()
            tasks.update(callback_tasks.values())

            if tasks:
                closeout_task = asyncio.create_task(asyncio.wait(tasks))

                while not closeout_task.done():
                    try:
                        await asyncio.shield(closeout_task)
                    except asyncio.CancelledError:
                        pass

    # manage state
    @property
    def power_state(self):
        return self._power_state

    @property
    def current_appId(self):
        return self._current_appId

    @property
    def muted(self):
        return self._muted

    @property
    def volume(self):
        return self._volume

    @property
    def current_channel(self):
        return self._current_channel

    @property
    def channel_info(self):
        return self._channel_info

    @property
    def channels(self):
        return self._channels

    @property
    def apps(self):
        return self._apps

    @property
    def inputs(self):
        return self._extinputs

    @property
    def system_info(self):
        return self._system_info

    @property
    def software_info(self):
        return self._software_info

    @property
    def sound_output(self):
        return self._sound_output

    @property
    def picture_settings(self):
        return self._picture_settings

    @property
    def is_on(self):
        state = self._power_state.get("state")
        if state == "Unknown":
            # fallback to current app id for some older webos versions which don't support explicit power state
            if self._current_appId in [None, ""]:
                return False
            else:
                return True
        elif state in [None, "Power Off", "Suspend", "Active Standby"]:
            return False
        else:
            return True

    @property
    def is_screen_on(self):
        if self.is_on:
            return self._power_state.get("state") != "Screen Off"
        return False

    async def register_state_update_callback(self, callback):
        self.state_update_callbacks.append(callback)
        if self.doStateUpdate:
            await callback()

    def unregister_state_update_callback(self, callback):
        if callback in self.state_update_callbacks:
            self.state_update_callbacks.remove(callback)

    def clear_state_update_callbacks(self):
        self.state_update_callbacks = []

    async def do_state_update_callbacks(self):
        callbacks = set()
        for callback in self.state_update_callbacks:
            callbacks.add(callback())

        if callbacks:
            await asyncio.gather(*callbacks)

    async def set_power_state(self, payload):
        self._power_state = payload

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_current_app_state(self, appId):
        """Set current app state variable.  This function also handles subscriptions to current channel and channel list, since the current channel subscription can only succeed when Live TV is running, and the channel list subscription can only succeed after channels have been configured."""
        self._current_appId = appId

        if self._channels is None:
            try:
                await self.subscribe_channels(self.set_channels_state)
            except PyLGTVCmdException:
                pass

        if appId == "com.webos.app.livetv" and self._current_channel is None:
            try:
                await self.subscribe_current_channel(self.set_current_channel_state)
            except PyLGTVCmdException:
                pass

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_muted_state(self, muted):
        self._muted = muted

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_volume_state(self, volume):
        self._volume = volume

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_channels_state(self, channels):
        self._channels = channels

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_current_channel_state(self, channel):
        """Set current channel state variable.  This function also handles the channel info subscription, since that call may fail if channel information is not available when it's called."""

        self._current_channel = channel

        if self._channel_info is None:
            try:
                await self.subscribe_channel_info(self.set_channel_info_state)
            except PyLGTVCmdException:
                pass

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_channel_info_state(self, channel_info):
        self._channel_info = channel_info

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_apps_state(self, payload):
        apps = payload.get("launchPoints")
        if apps is not None:
            self._apps = {}
            for app in apps:
                self._apps[app["id"]] = app
        else:
            change = payload["change"]
            app_id = payload["id"]
            if change == "removed":
                del self._apps[app_id]
            else:
                self._apps[app_id] = payload

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_inputs_state(self, extinputs):
        self._extinputs = {}
        for extinput in extinputs:
            self._extinputs[extinput["appId"]] = extinput

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_sound_output_state(self, sound_output):
        self._sound_output = sound_output

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    async def set_picture_settings_state(self, picture_settings):
        self._picture_settings = picture_settings

        if self.state_update_callbacks and self.doStateUpdate:
            await self.do_state_update_callbacks()

    # low level request handling

    async def command(self, request_type, uri, payload=None, uid=None):
        """Build and send a command."""
        if uid is None:
            uid = self.command_count
            self.command_count += 1

        if payload is None:
            payload = {}

        message = {
            "id": uid,
            "type": request_type,
            "uri": f"ssap://{uri}",
            "payload": payload,
        }

        if self.connection is None:
            raise PyLGTVCmdException("Not connected, can't execute command.")

        await self.connection.send(json.dumps(message))

    async def request(self, uri, payload=None, cmd_type="request", uid=None):
        """Send a request and wait for response."""
        if uid is None:
            uid = self.command_count
            self.command_count += 1
        res = asyncio.Future()
        self.futures[uid] = res
        try:
            await self.command(cmd_type, uri, payload, uid)
        except (asyncio.CancelledError, PyLGTVCmdException):
            del self.futures[uid]
            raise
        try:
            response = await res
        except asyncio.CancelledError:
            if uid in self.futures:
                del self.futures[uid]
            raise
        del self.futures[uid]

        payload = response.get("payload")
        if payload is None:
            raise PyLGTVCmdException(f"Invalid request response {response}")

        returnValue = payload.get("returnValue") or payload.get("subscribed")

        if response.get("type") == "error":
            error = response.get("error")
            if error == "404 no such service or method":
                raise PyLGTVServiceNotFoundError(error)
            else:
                raise PyLGTVCmdError(response)
        elif returnValue is None:
            raise PyLGTVCmdException(f"Invalid request response {response}")
        elif not returnValue:
            raise PyLGTVCmdException(f"Request failed with response {response}")

        return payload

    async def subscribe(self, callback, uri, payload=None):
        """Subscribe to updates."""
        uid = self.command_count
        self.command_count += 1
        self.callbacks[uid] = callback
        try:
            return await self.request(
                uri, payload=payload, cmd_type="subscribe", uid=uid
            )
        except Exception:
            del self.callbacks[uid]
            raise

    async def input_command(self, message):
        inputws = None
        try:
            # open additional connection needed to send button commands
            # the url is dynamically generated and returned from the ep.INPUT_SOCKET
            # endpoint on the main connection
            if self.input_connection is None:
                sockres = await self.request(ep.INPUT_SOCKET)
                inputsockpath = sockres.get("socketPath")
                inputws = await asyncio.wait_for(
                    websockets.connect(
                        inputsockpath,
                        ping_interval=None,
                        close_timeout=self.timeout_connect,
                    ),
                    timeout=self.timeout_connect,
                )

                comm='''
                if self.ping_interval is not None:
                    handler_tasks.add(
                        asyncio.create_task(
                            self.ping_handler(
                                inputws, self.ping_interval, self.ping_timeout
                            )
                        )
                    )
                '''
                self.input_connection = inputws

            if self.input_connection is None:
                raise PyLGTVCmdException("Couldn't execute input command.")

            await self.input_connection.send(message)

        except Exception as ex:
            if not self.connect_result.done():
                self.connect_result.set_exception(ex)

    # high level request handling

    async def button(self, name):
        """Send button press command."""

        message = f"type:button\nname:{name}\n\n"
        await self.input_command(message)

    async def move(self, dx, dy, down=0):
        """Send cursor move command."""

        message = f"type:move\ndx:{dx}\ndy:{dy}\ndown:{down}\n\n"
        await self.input_command(message)

    async def click(self):
        """Send cursor click command."""

        message = f"type:click\n\n"
        await self.input_command(message)

    async def scroll(self, dx, dy):
        """Send scroll command."""

        message = f"type:scroll\ndx:{dx}\ndy:{dy}\n\n"
        await self.input_command(message)

    async def send_message(self, message, icon_path=None):
        """Show a floating message."""
        icon_encoded_string = ""
        icon_extension = ""

        if icon_path is not None:
            icon_extension = os.path.splitext(icon_path)[1][1:]
            with open(icon_path, "rb") as icon_file:
                icon_encoded_string = base64.b64encode(icon_file.read()).decode("ascii")

        return await self.request(
            ep.SHOW_MESSAGE,
            {
                "message": message,
                "iconData": icon_encoded_string,
                "iconExtension": icon_extension,
            },
        )

    async def get_power_state(self):
        """Get current power state."""
        return await self.request(ep.GET_POWER_STATE)

    async def subscribe_power_state(self, callback):
        """Subscribe to current power state."""
        return await self.subscribe(callback, ep.GET_POWER_STATE)

    # Apps
    async def get_apps(self):
        """Return all apps."""
        res = await self.request(ep.GET_APPS)
        return res.get("launchPoints")

    async def subscribe_apps(self, callback):
        """Subscribe to changes in available apps."""
        return await self.subscribe(callback, ep.GET_APPS)

    async def get_current_app(self):
        """Get the current app id."""
        res = await self.request(ep.GET_CURRENT_APP_INFO)
        return res.get("appId")

    async def subscribe_current_app(self, callback):
        """Subscribe to changes in the current app id."""

        async def current_app(payload):
            await callback(payload.get("appId"))

        return await self.subscribe(current_app, ep.GET_CURRENT_APP_INFO)

    async def launch_app(self, app):
        """Launch an app."""
        return await self.request(ep.LAUNCH, {"id": app})

    async def launch_app_with_params(self, app, params):
        """Launch an app with parameters."""
        return await self.request(ep.LAUNCH, {"id": app, "params": params})

    async def launch_app_with_content_id(self, app, contentId):
        """Launch an app with contentId."""
        return await self.request(ep.LAUNCH, {"id": app, "contentId": contentId})

    async def close_app(self, app):
        """Close the current app."""
        return await self.request(ep.LAUNCHER_CLOSE, {"id": app})

    # Services
    async def get_services(self):
        """Get all services."""
        res = await self.request(ep.GET_SERVICES)
        return res.get("services")

    async def get_software_info(self):
        """Return the current software status."""
        return await self.request(ep.GET_SOFTWARE_INFO)

    async def get_system_info(self):
        """Return the system information."""
        return await self.request(ep.GET_SYSTEM_INFO)

    async def power_off(self):
        """Power off TV."""

        # protect against turning tv back on if it is off
        self._power_state = await self.get_power_state()
        if not self.is_on:
            return

        # if tv is shutting down and standby+ option is not enabled,
        # response is unreliable, so don't wait for one,
        await self.command("request", ep.POWER_OFF)

    async def power_on(self):
        """Play media."""
        return await self.request(ep.POWER_ON)

    async def turn_screen_off(self):
        """Turn TV Screen off."""
        await self.command("request", ep.TURN_OFF_SCREEN)

    async def turn_screen_on(self):
        """Turn TV Screen on."""
        await self.command("request", ep.TURN_ON_SCREEN)

    # 3D Mode
    async def turn_3d_on(self):
        """Turn 3D on."""
        return await self.request(ep.SET_3D_ON)

    async def turn_3d_off(self):
        """Turn 3D off."""
        return await self.request(ep.SET_3D_OFF)

    # Inputs
    async def get_inputs(self):
        """Get all inputs."""
        res = await self.request(ep.GET_INPUTS)
        return res.get("devices")

    async def subscribe_inputs(self, callback):
        """Subscribe to changes in available inputs."""

        async def inputs(payload):
            await callback(payload.get("devices"))

        return await self.subscribe(inputs, ep.GET_INPUTS)

    async def get_input(self):
        """Get current input."""
        return await self.get_current_app()

    async def set_input(self, input):
        """Set the current input."""
        return await self.request(ep.SET_INPUT, {"inputId": input})

    # Audio
    async def get_audio_status(self):
        """Get the current audio status"""
        return await self.request(ep.GET_AUDIO_STATUS)

    async def get_muted(self):
        """Get mute status."""
        status = await self.get_audio_status()
        return status.get("mute")

    async def subscribe_muted(self, callback):
        """Subscribe to changes in the current mute status."""

        async def muted(payload):
            await callback(payload.get("mute"))

        return await self.subscribe(muted, ep.GET_AUDIO_STATUS)

    async def set_mute(self, mute):
        """Set mute."""
        return await self.request(ep.SET_MUTE, {"mute": mute})

    async def get_volume(self):
        """Get the current volume."""
        res = await self.request(ep.GET_VOLUME)
        return res.get("volumeStatus", res).get("volume")

    async def subscribe_volume(self, callback):
        """Subscribe to changes in the current volume."""

        async def volume(payload):
            await callback(payload.get("volumeStatus", payload).get("volume"))

        return await self.subscribe(volume, ep.GET_VOLUME)

    async def set_volume(self, volume):
        """Set volume."""
        volume = max(0, volume)
        return await self.request(ep.SET_VOLUME, {"volume": volume})

    async def volume_up(self):
        """Volume up."""
        return await self._volume_step(ep.VOLUME_UP)

    async def volume_down(self):
        """Volume down."""
        return await self._volume_step(ep.VOLUME_DOWN)

    async def _volume_step(self, endpoint):
        """Volume step and conditionally sleep afterwards if a consecutive volume step shouldn't be possible to perform immediately after."""
        if (
            self.sound_output in SOUND_OUTPUTS_TO_DELAY_CONSECUTIVE_VOLUME_STEPS
            and self._volume_step_delay is not None
        ):
            async with self._volume_step_lock:
                response = await self.request(endpoint)
                await asyncio.sleep(self._volume_step_delay.total_seconds())
                return response
        else:
            return await self.request(endpoint)

    # TV Channel
    async def channel_up(self):
        """Channel up."""
        return await self.request(ep.TV_CHANNEL_UP)

    async def channel_down(self):
        """Channel down."""
        return await self.request(ep.TV_CHANNEL_DOWN)

    async def get_channels(self):
        """Get list of tv channels."""
        res = await self.request(ep.GET_TV_CHANNELS)
        return res.get("channelList")

    async def subscribe_channels(self, callback):
        """Subscribe to list of tv channels."""

        async def channels(payload):
            await callback(payload.get("channelList"))

        return await self.subscribe(channels, ep.GET_TV_CHANNELS)

    async def get_current_channel(self):
        """Get the current tv channel."""
        return await self.request(ep.GET_CURRENT_CHANNEL)

    async def subscribe_current_channel(self, callback):
        """Subscribe to changes in the current tv channel."""
        return await self.subscribe(callback, ep.GET_CURRENT_CHANNEL)

    async def get_channel_info(self):
        """Get the current channel info."""
        return await self.request(ep.GET_CHANNEL_INFO)

    async def subscribe_channel_info(self, callback):
        """Subscribe to current channel info."""
        return await self.subscribe(callback, ep.GET_CHANNEL_INFO)

    async def set_channel(self, channel):
        """Set the current channel."""
        return await self.request(ep.SET_CHANNEL, {"channelId": channel})

    async def get_sound_output(self):
        """Get the current audio output."""
        res = await self.request(ep.GET_SOUND_OUTPUT)
        return res.get("soundOutput")

    async def subscribe_sound_output(self, callback):
        """Subscribe to changes in current audio output."""

        async def sound_output(payload):
            await callback(payload.get("soundOutput"))

        return await self.subscribe(sound_output, ep.GET_SOUND_OUTPUT)

    async def change_sound_output(self, output):
        """Change current audio output."""
        return await self.request(ep.CHANGE_SOUND_OUTPUT, {"output": output})

    # Media control
    async def play(self):
        """Play media."""
        return await self.request(ep.MEDIA_PLAY)

    async def pause(self):
        """Pause media."""
        return await self.request(ep.MEDIA_PAUSE)

    async def stop(self):
        """Stop media."""
        return await self.request(ep.MEDIA_STOP)

    async def close(self):
        """Close media."""
        return await self.request(ep.MEDIA_CLOSE)

    async def rewind(self):
        """Rewind media."""
        return await self.request(ep.MEDIA_REWIND)

    async def fast_forward(self):
        """Fast Forward media."""
        return await self.request(ep.MEDIA_FAST_FORWARD)

    # Keys
    async def send_enter_key(self):
        """Send enter key."""
        return await self.request(ep.SEND_ENTER)

    async def send_delete_key(self):
        """Send delete key."""
        return await self.request(ep.SEND_DELETE)

    # Text entry
    async def insert_text(self, text, replace=False):
        """Insert text into field, optionally replace existing text."""
        return await self.request(ep.INSERT_TEXT, {"text": text, "replace": replace})

    # Web
    async def open_url(self, url):
        """Open URL."""
        return await self.request(ep.OPEN, {"target": url})

    async def close_web(self):
        """Close web app."""
        return await self.request(ep.CLOSE_WEB_APP)

    # Emulated button presses
    async def left_button(self):
        """left button press."""
        await self.button(btn.LEFT)

    async def right_button(self):
        """right button press."""
        await self.button(btn.RIGHT)

    async def down_button(self):
        """down button press."""
        await self.button(btn.DOWN)

    async def up_button(self):
        """up button press."""
        await self.button(btn.UP)

    async def home_button(self):
        """home button press."""
        await self.button(btn.HOME)

    async def back_button(self):
        """back button press."""
        await self.button(btn.BACK)

    async def ok_button(self):
        """ok button press."""
        await self.button(btn.ENTER)

    async def dash_button(self):
        """dash button press."""
        await self.button(btn.DASH)

    async def info_button(self):
        """info button press."""
        await self.button(btn.INFO)

    async def asterisk_button(self):
        """asterisk button press."""
        await self.button(btn.ASTERISK)

    async def cc_button(self):
        """cc button press."""
        await self.button(btn.CC)

    async def exit_button(self):
        """exit button press."""
        await self.button(btn.EXIT)

    async def mute_button(self):
        """mute button press."""
        await self.button(btn.MUTE)

    async def red_button(self):
        """red button press."""
        await self.button(btn.RED)

    async def green_button(self):
        """green button press."""
        await self.button(btn.GREEN)

    async def blue_button(self):
        """blue button press."""
        await self.button(btn.BLUE)

    async def volume_up_button(self):
        """volume up button press."""
        await self.button(btn.VOLUMEUP)

    async def volume_down_button(self):
        """volume down button press."""
        await self.button(btn.VOLUMEDOWN)

    async def channel_up_button(self):
        """channel up button press."""
        await self.button(btn.CHANNELUP)

    async def channel_down_button(self):
        """channel down button press."""
        await self.button(btn.CHANNELDOWN)

    async def play_button(self):
        """play button press."""
        await self.button(btn.PLAY)

    async def pause_button(self):
        """pause button press."""
        await self.button(btn.PAUSE)

    async def number_button(self, num):
        """numeric button press."""
        if not (num >= 0 and num <= 9):
            raise ValueError

        await self.button(f"""{num}""")

    async def luna_request(self, uri, params):
        """luna api call."""
        # n.b. this is a hack which abuses the alert API
        # to call the internal luna API which is otherwise
        # not exposed through the websocket interface
        # An important limitation is that any returned
        # data is not accessible

        # set desired action for click, fail and close
        # for redundancy/robustness

        lunauri = f"luna://{uri}"

        buttons = [{"label": "", "onClick": lunauri, "params": params}]
        payload = {
            "message": " ",
            "buttons": buttons,
            "onclose": {"uri": lunauri, "params": params},
            "onfail": {"uri": lunauri, "params": params},
        }

        ret = await self.request(ep.CREATE_ALERT, payload)
        alertId = ret.get("alertId")
        if alertId is None:
            raise PyLGTVCmdException("Invalid alertId")

        return await self.request(ep.CLOSE_ALERT, payload={"alertId": alertId})

    async def set_current_picture_mode(self, pic_mode):
        """Set picture mode for current input, dynamic range and 3d mode.

        Known picture modes are: cinema, eco, expert1, expert2, game,
        normal, photo, sports, technicolor, vivid, hdrEffect,  hdrCinema,
        hdrCinemaBright, hdrExternal, hdrGame, hdrStandard, hdrTechnicolor,
        hdrVivid, dolbyHdrCinema, dolbyHdrCinemaBright, dolbyHdrDarkAmazon,
        dolbyHdrGame, dolbyHdrStandard, dolbyHdrVivid, dolbyStandard

        Likely not all modes are valid for all tv models.
        """

        uri = "com.webos.settingsservice/setSystemSettings"

        params = {"category": "picture", "settings": {"pictureMode": pic_mode}}

        return await self.luna_request(uri, params)

    async def set_picture_mode(
        self, pic_mode, tv_input, dynamic_range="sdr", stereoscopic="2d"
    ):
        """Set picture mode for specific input, dynamic range and 3d mode.

        Known picture modes are: cinema, eco, expert1, expert2, game,
        normal, photo, sports, technicolor, vivid, hdrEffect,  hdrCinema,
        hdrCinemaBright, hdrExternal, hdrGame, hdrStandard, hdrTechnicolor,
        hdrVivid, dolbyHdrCinema, dolbyHdrCinemaBright, dolbyHdrDarkAmazon,
        dolbyHdrGame, dolbyHdrStandard, dolbyHdrVivid, dolbyStandard

        Known inputs are: atv, av1, av2, camera, comp1, comp2, comp3,
        default, dtv, gallery, hdmi1, hdmi2, hdmi3, hdmi4,
        hdmi1_pc, hdmi2_pc, hdmi3_pc, hdmi4_pc, ip, movie,
        photo, pictest, rgb, scart, smhl

        Known dynamic range modes are: sdr, hdr, technicolorHdr, dolbyHdr

        Known stereoscopic modes are: 2d, 3d

        Likely not all inputs and modes are valid for all tv models.
        """

        uri = "com.webos.settingsservice/setSystemSettings"

        params = {
            "category": f"picture${tv_input}.x.{stereoscopic}.{dynamic_range}",
            "settings": {"pictureMode": pic_mode},
        }

        return await self.luna_request(uri, params)

    async def set_current_picture_settings(self, settings):
        """Set picture settings for current picture mode, input, dynamic range and 3d mode.

        A possible list of settings and example values are below (not all settings are applicable
        for all modes and/or tv models):

        "adjustingLuminance": [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0
        ],
        "backlight": "80",
        "blackLevel": {
            "ntsc": "auto",
            "ntsc443": "auto",
            "pal": "auto",
            "pal60": "auto",
            "palm": "auto",
            "paln": "auto",
            "secam": "auto",
            "unknown": "auto"
        },
        "brightness": "50",
        "color": "50",
        "colorFilter": "off",
        "colorGamut": "auto",
        "colorManagementColorSystem": "red",
        "colorManagementHueBlue": "0",
        "colorManagementHueCyan": "0",
        "colorManagementHueGreen": "0",
        "colorManagementHueMagenta": "0",
        "colorManagementHueRed": "0",
        "colorManagementHueYellow": "0",
        "colorManagementLuminanceBlue": "0",
        "colorManagementLuminanceCyan": "0",
        "colorManagementLuminanceGreen": "0",
        "colorManagementLuminanceMagenta": "0",
        "colorManagementLuminanceRed": "0",
        "colorManagementLuminanceYellow": "0",
        "colorManagementSaturationBlue": "0",
        "colorManagementSaturationCyan": "0",
        "colorManagementSaturationGreen": "0",
        "colorManagementSaturationMagenta": "0",
        "colorManagementSaturationRed": "0",
        "colorManagementSaturationYellow": "0",
        "colorTemperature": "0",
        "contrast": "80",
        "dynamicColor": "off",
        "dynamicContrast": "off",
        "edgeEnhancer": "on",
        "expertPattern": "off",
        "externalPqlDbType": "none",
        "gamma": "high2",
        "grassColor": "0",
        "hPosition": "0",
        "hSharpness": "10",
        "hSize": "0",
        "hdrDynamicToneMapping": "on",
        "hdrLevel": "medium",
        "localDimming": "medium",
        "motionEyeCare": "off",
        "motionPro": "off",
        "mpegNoiseReduction": "off",
        "noiseReduction": "off",
        "realCinema": "on",
        "sharpness": "10",
        "skinColor": "0",
        "skyColor": "0",
        "superResolution": "off",
        "tint": "0",
        "truMotionBlur": "10",
        "truMotionJudder": "0",
        "truMotionMode": "user",
        "vPosition": "0",
        "vSharpness": "10",
        "vSize": "0",
        "whiteBalanceApplyAllInputs": "off",
        "whiteBalanceBlue": [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0
        ],
        "whiteBalanceBlueGain": "0",
        "whiteBalanceBlueOffset": "0",
        "whiteBalanceCodeValue": "19",
        "whiteBalanceColorTemperature": "warm2",
        "whiteBalanceGreen": [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0
        ],
        "whiteBalanceGreenGain": "0",
        "whiteBalanceGreenOffset": "0",
        "whiteBalanceIre": "100",
        "whiteBalanceLuminance": "130",
        "whiteBalanceMethod": "2",
        "whiteBalancePattern": "outer",
        "whiteBalancePoint": "high",
        "whiteBalanceRed": [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0
        ],
        "whiteBalanceRedGain": "0",
        "whiteBalanceRedOffset": "0",
        "xvycc": "auto"


        """

        uri = "com.webos.settingsservice/setSystemSettings"

        params = {"category": "picture", "settings": settings}

        return await self.luna_request(uri, params)

    async def set_picture_settings(
        self, settings, pic_mode, tv_input, stereoscopic="2d"
    ):
        """Set picture settings for specific picture mode, input, and 3d mode."""

        uri = "com.webos.settingsservice/setSystemSettings"

        params = {
            "category": f"picture${tv_input}.{pic_mode}.{stereoscopic}.x",
            "settings": settings,
        }

        return await self.luna_request(uri, params)

    async def set_other_settings(self, settings):
        """Set other settings.

        A possible list of settings and example values are below (not all settings are applicable
        for all modes and/or tv models):

        "amazonHotkeyIsActive": true,
        "appReturn": "",
        "care365": {
            "accountName": "",
            "accountNumber": "",
            "userAgreementLocation": "",
            "userAgreementVersion": "",
            "value": "off"
        },
        "colorimetryHDMI1": "auto",
        "colorimetryHDMI2": "auto",
        "colorimetryHDMI3": "auto",
        "colorimetryHDMI4": "auto",
        "cursorAutoRemover": "on",
        "dolbyVSVDBVerHDMI1": "v1",
        "dolbyVSVDBVerHDMI2": "v1",
        "dolbyVSVDBVerHDMI3": "v1",
        "dolbyVSVDBVerHDMI4": "v1",
        "eotfHDMI1": "auto",
        "eotfHDMI2": "auto",
        "eotfHDMI3": "auto",
        "eotfHDMI4": "auto",
        "epgRowCount": "1",
        "flickerPatternCtrl": false,
        "freesyncLCDHDMI1": "off",
        "freesyncLCDHDMI2": "off",
        "freesyncLCDHDMI3": "off",
        "freesyncLCDHDMI4": "off",
        "freesyncOLEDHDMI1": "off",
        "freesyncOLEDHDMI2": "off",
        "freesyncOLEDHDMI3": "off",
        "freesyncOLEDHDMI4": "off",
        "freesyncSupport": "off",
        "freeviewTnCPopup": "off",
        "gameOptimizationHDMI1": "on",
        "gameOptimizationHDMI2": "on",
        "gameOptimizationHDMI3": "on",
        "gameOptimizationHDMI4": "on",
        "hdmiPcMode": {
            "hdmi1": false,
            "hdmi2": false,
            "hdmi3": false,
            "hdmi4": false
        },
        "homeEffectVersion": [
            {
                "id": "Christmas",
                "version": 1.0
            },
            {
                "id": "Halloween",
                "version": 1.0
            }
        ],
        "isFirstCapture": "true",
        "isfUpdated": "false",
        "lowLevelAdjustment": 0,
        "masterLuminanceLevel": "540nit",
        "masteringColorHDMI1": "auto",
        "masteringColorHDMI2": "auto",
        "masteringColorHDMI3": "auto",
        "masteringColorHDMI4": "auto",
        "masteringPeakHDMI1": "auto",
        "masteringPeakHDMI2": "auto",
        "masteringPeakHDMI3": "auto",
        "masteringPeakHDMI4": "auto",
        "maxCLLHDMI1": "auto",
        "maxCLLHDMI2": "auto",
        "maxCLLHDMI3": "auto",
        "maxCLLHDMI4": "auto",
        "maxFALLHDMI1": "auto",
        "maxFALLHDMI2": "auto",
        "maxFALLHDMI3": "auto",
        "maxFALLHDMI4": "auto",
        "netflixHotkeyIsActive": true,
        "quickSettingsMenuList": [
            "QuickSettings_picture_button",
            "QuickSettings_soundMode_button",
            "QuickSettings_soundOut_button",
            "QuickSettings_timer_button",
            "QuickSettings_network_button",
            "QuickSettings_menu_button"
        ],
        "screenRemoteAutoShow": "true",
        "screenRemoteExpanded": "false",
        "screenRemotePosition": "right",
        "simplinkAutoPowerOn": "on",
        "simplinkEnable": "off",
        "supportAirplay": false,
        "supportBnoModel": false,
        "ueiEnable": "off",
        "uhdDeepColor8kHDMI1": "off",
        "uhdDeepColor8kHDMI2": "off",
        "uhdDeepColor8kHDMI3": "off",
        "uhdDeepColor8kHDMI4": "off",
        "uhdDeepColorAutoStatusHDMI1": "none",
        "uhdDeepColorAutoStatusHDMI2": "none",
        "uhdDeepColorAutoStatusHDMI3": "none",
        "uhdDeepColorAutoStatusHDMI4": "none",
        "uhdDeepColorHDMI1": "off",
        "uhdDeepColorHDMI2": "off",
        "uhdDeepColorHDMI3": "off",
        "uhdDeepColorHDMI4": "off"

        """

        uri = "com.webos.settingsservice/setSystemSettings"

        params = {"category": "other", "settings": settings}

        return await self.luna_request(uri, params)

    async def set_configs(self, settings):
        """Set config settings.

        Example:

        "tv.model.motionProMode": "OLED Motion",
        "tv.model.motionProMode": "OLED Motion Pro"

        """

        uri = "com.webos.service.config/setConfigs"

        params = {"configs": settings}

        return await self.luna_request(uri, params)

    async def show_screen_saver(self):
        uri = "com.webos.service.tvpower/power/turnOnScreenSaver"

        return await self.luna_request(uri, {})

    async def get_system_settings(self, category="option", keys=["audioGuidance"]):
        """Get system settings.

        Most of the settings are not exposed via this call, valid settings:
        /usr/palm/services/com.webos.service.apiadapter/adapters/settings/valid-settings.js
        """

        payload = {"category": category, "keys": keys}
        ret = await self.request(ep.GET_SYSTEM_SETTINGS, payload=payload)
        return ret

    async def get_picture_settings(
        self, keys=["contrast", "backlight", "brightness", "color"]
    ):
        ret = await self.get_system_settings("picture", keys)
        return ret["settings"]

    async def subscribe_picture_settings(
        self, callback, keys=["contrast", "backlight", "brightness", "color"]
    ):
        async def settings(payload):
            await callback(payload.get("settings"))

        payload = {"category": "picture", "keys": keys}
        return await self.subscribe(settings, ep.GET_SYSTEM_SETTINGS, payload=payload)
