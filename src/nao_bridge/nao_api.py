"""Nao API Module.

This module provides an API for interacting with a Nao robot.
It supports both real and fake robot modes, with comprehensive error handling and logging.
"""

import asyncio
import base64
import logging
from dataclasses import dataclass
import random
from typing import Callable

try:
    import qi
    QI_MISSING = False
except ImportError:
    QI_MISSING = True

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class LocalizedString:
    en_US: str
    fr_FR: str

@dataclass
class NaoBehavior:
    package_uuid: str
    behavior_path: str
    behavior_name: str
    localized_name: LocalizedString
    description: str
    tags: list[str]

@dataclass
class BehaviorInfos:
    id: str
    behavior_name: str
    localized_name: LocalizedString
    description: str

class NaoAPI:
    """API for interacting with a Nao robot.

    This class provides methods to control various aspects of the Nao robot,
    including speech, movement, and behaviors. It can operate in both real
    and fake robot modes.
    """

    # Constants
    POSTURE_SPEED = 0.8
    POSTURE_MAX_TRIES = 3

    def __init__(self,
                 fake_robot: bool,
                 memory_callback_touch: Callable[[str, float], None],
                 joints_callback: Callable[[list[str], list[float]], None],
                 audio_callback: Callable[[int, int, int, bytes], None],
                 nao_ip: str = "", nao_port: int = 9559) -> None:
        """Initialize the NaoAPI instance.

        Args:
            fake_robot: Whether to use fake robot mode
            memory_callback_touch: Callback for memory touch events
            joints_callback: Callback for joints data
            audio_callback: Callback for audio data
            nao_ip: Robot IP address
            nao_port: Robot port number
        """

        self.fake_robot = fake_robot
        self.memory_callback_touch = memory_callback_touch
        self.joints_callback = joints_callback
        self.audio_callback = audio_callback
        self.nao_ip = nao_ip
        self.nao_port = nao_port

        self.async_loop = None

        self.connected = False
        self.qi_session = None
        self.service_name = "NaoAPI"
        self.service_id = None

        self.memory = None
        self.autonomous_life = None
        self.package_manager = None
        self.behavior_manager = None
        self.motion = None
        self.robot_posture = None
        self.leds = None
        self.tts = None
        self.animated_speech = None
        self.basic_awareness = None
        self.audio_device = None

        self._all_behaviors = list[NaoBehavior]()
        self._dance_behaviors = dict[str, BehaviorInfos]()
        self._expressive_reaction_behaviors = dict[str, list[BehaviorInfos]]()
        self._body_action_behaviors = dict[str, BehaviorInfos]()
        self._app_behaviors = dict[str, BehaviorInfos]()

        self.current_dances = list[str]()
        self.current_expressive_reactions = dict[str, str]()
        self.current_body_actions = list[str]()
        self.current_apps = list[str]()
        self.current_behaviors = list[str]()

        self.joints_data_sync_activated = False

    #region Connection management
    async def connect(self) -> bool:
        """Connect to the Nao robot.

        Returns:
            bool: True if connection successful, False otherwise
        """
        logger.debug("Connecting to Nao")
        self.connected = False
        self.async_loop = asyncio.get_event_loop()

        if self.fake_robot:
            logger.info("Using a fake robot")
            await self._retrieve_fake_behaviors()
            return True

        if QI_MISSING:
            logger.error("Could not import qi, will act as if nao is in fake robot mode")
            self.fake_robot = True
            await self._retrieve_fake_behaviors()
            return True

        if not self.nao_ip or self.nao_port == 0:
            logger.error("Not a fake robot but ip or port is not set")
            await self._retrieve_fake_behaviors()
            return False

        if not self._initialize_qi_session():
            return False

        self._initialize_services()
        if self.memory_callback_touch:
            self._subscribe_to_memory_events()
        if self.audio_callback:
            self._subscribe_to_audio_device()
        if self.joints_callback:
            self._start_joints_data_loop()

        await self._retrieve_behaviors()

        self.connected = True
        return True

    async def disconnect(self) -> bool:
        """Disconnect from the Nao robot."""
        logger.debug("Disconnecting from Nao")

        if (self.fake_robot):
            return True

        if (not self.connected):
            return True

        if self.memory_callback_touch:
            self._unsubscribe_to_memory_events()
        if self.audio_callback:
            self._unsubscribe_to_audio_device()
        if self.joints_callback:
            self._stop_joints_data_loop()
        self._close_qi_session()

        self.connected = False
        return True

    def _check_connection_for_return(self, function_name: str) -> tuple[bool, bool]:
        if self.fake_robot:
            return (True, True)
        if not self.connected:
            logger.error(f"{function_name} failed because not connected to Nao")
            return (True, False)
        return (False, False)

    #region Qi session & services
    def _initialize_qi_session(self) -> bool:
        connection_url = "tcp://" + self.nao_ip + ":" + str(self.nao_port)
        max_tries = 10
        for i in range(0,max_tries):
            try:
                self.qi_session = qi.Session()
                self.qi_session.connect(connection_url)
                logger.debug("Successfully initialized qi session")
                return True
            except Exception as e:
                if i == max_tries - 1:
                    logger.warning(f"Failed to connect session with error = {e}, retrying")
                    logger.error(f"Failed to connect session after {max_tries} tries")
                    return False
                else:
                    logger.warning(f"Failed to connect session with error = {e}, retrying")

    def _close_qi_session(self) -> None:
        self.qi_session.close()
        self.qi_session = None

    def _initialize_services(self) -> None:
        try:
            self.memory = self.qi_session.service("ALMemory")
            self.autonomous_life = self.qi_session.service("ALAutonomousLife")
            self.package_manager = self.qi_session.service("PackageManager")
            self.behavior_manager = self.qi_session.service("ALBehaviorManager")
            self.motion = self.qi_session.service("ALMotion")
            self.robot_posture = self.qi_session.service("ALRobotPosture")
            self.leds = self.qi_session.service("ALLeds")
            self.tts = self.qi_session.service("ALTextToSpeech")
            self.animated_speech = self.qi_session.service("ALAnimatedSpeech")
            self.basic_awareness = self.qi_session.service("ALBasicAwareness")
            self.audio_device = self.qi_session.service("ALAudioDevice")
            logger.debug("All services initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize services: {e}")
    #endregion

    #region Memory & Touch
    def _subscribe_to_memory_events(self) -> None:
        self.subscriber_front_touch = self.memory.subscriber("FrontTactilTouched")
        self.subscriber_middle_touch = self.memory.subscriber("MiddleTactilTouched")
        self.subscriber_rear_touch = self.memory.subscriber("RearTactilTouched")

        self.sub_front_touch = self.subscriber_front_touch.signal.connect(
            lambda value: self._memory_callback_touch("FrontTactilTouched", value))
        self.sub_middle_touch = self.subscriber_middle_touch.signal.connect(
            lambda value: self._memory_callback_touch("MiddleTactilTouched", value))
        self.sub_rear_touch = self.subscriber_rear_touch.signal.connect(
            lambda value: self._memory_callback_touch("RearTactilTouched", value))

    def _unsubscribe_to_memory_events(self) -> None:
        self.subscriber_front_touch.signal.disconnect(self.sub_front_touch)
        self.subscriber_middle_touch.signal.disconnect(self.sub_middle_touch)
        self.subscriber_rear_touch.signal.disconnect(self.sub_rear_touch)

    def _memory_callback_touch(self, key, value):
        asyncio.run_coroutine_threadsafe(self.memory_callback_touch(key, value), self.async_loop)
    #endregion

    #region Audio
    def _subscribe_to_audio_device(self) -> None:
        self.service_id = self.qi_session.registerService(self.service_name, self)
        self.audio_device.setClientPreferences(self.service_name, 16000, 3, 0)
        self.audio_device.subscribe(self.service_name)

    def _unsubscribe_to_audio_device(self) -> None:
        self.audio_device.unsubscribe(self.service_name)
        self.qi_session.unregisterService(self.service_id)

    # This method needs to be named "processRemote" for the subscription callback to work
    def processRemote(self, nbOfChannels, nbOfSamplesByChannel, timeStamp, inputBuffer):
        # base64-encode buffer
        b64 = base64.b64encode(inputBuffer).decode('ascii')
        asyncio.run_coroutine_threadsafe(self.audio_callback(16000, nbOfChannels, nbOfSamplesByChannel, b64), self.async_loop)
    #endregion

    #region Joints
    def _start_joints_data_loop(self) -> None:
        logger.debug("Starting joints data sending loop")
        self.joints_data_sync_activated = True
        asyncio.create_task(self._joints_data_loop())

    def _stop_joints_data_loop(self) -> None:
        logger.debug("Stopping joints data sending loop")
        self.joints_data_sync_activated = False

    async def _joints_data_loop(self):
        while self.joints_data_sync_activated:
            (joints_names, joints_angles) = self._get_joints_from_nao()
            await self.joints_callback(joints_names, joints_angles)
            await asyncio.sleep(0.2)

    def _get_joints_from_nao(self):
        joints_names = self.motion.getBodyNames("Body")
        joints_angles = self.motion.getAngles("Body", False)
        return (joints_names, joints_angles)
    #endregion

    #endregion

    #region API helpers
    async def async_api(func: Callable, *args, **kwargs) -> tuple[bool, any]:
        """Run a function asynchronously.
        
        Args:
            func: The function to run
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            return (True, await asyncio.to_thread(func, *args, **kwargs))
        except Exception as e:
            logger.error("Failed to run function: %s", e)
            return (False, None)
    #endregion

    #region Behaviors/Reactions/Actions retrieval
    async def _retrieve_behaviors(self) -> None:
        self._all_behaviors = await self._retrieve_all_nao_behaviors()
        self._dance_behaviors = self._retrieve_dance_behaviors(self._all_behaviors)
        self._expressive_reaction_behaviors = dict[str, list[BehaviorInfos]]()
        self._expressive_reaction_behaviors["Happy"] = self._retrieve_reactions_for_tag(self._all_behaviors, "Stand", "happy")
        self._expressive_reaction_behaviors["Proud"] = self._retrieve_reactions_for_tag(self._all_behaviors, "Stand", "proud")
        self._expressive_reaction_behaviors["Laugh"] = self._retrieve_reactions_for_tag(self._all_behaviors, "Stand", "laugh")
        self._expressive_reaction_behaviors["Sad"] = self._retrieve_reactions_for_tag(self._all_behaviors, "Stand", "sad")
        self._expressive_reaction_behaviors["HeadTouched"] = self._retrieve_reactions_for_head_touched(self._all_behaviors)
        self._body_action_behaviors = self._retrieve_body_actions(self._all_behaviors)
        self._app_behaviors = self._retrieve_app_behaviors(self._all_behaviors)

    async def _retrieve_fake_behaviors(self) -> None:
        self._dance_behaviors = self._get_fake_dance_behaviors()
        self._expressive_reaction_behaviors = self._get_fake_reaction_behaviors()
        self._body_action_behaviors = self._get_fake_body_action_behaviors()
        self._app_behaviors = self._get_fake_app_behaviors()


    async def _retrieve_all_nao_behaviors(self) -> list[NaoBehavior]:
        package_list = await asyncio.to_thread(self.package_manager.packages2)

        behavior_list = list[NaoBehavior]()
        for package in package_list:
            if ("elems" not in package or
                "contents" not in package["elems"] or
                "names" not in package["elems"] or
                "descriptions" not in package["elems"] or
                "behaviors" not in package["elems"]["contents"]):
                continue
            for package_behavior in package["elems"]["contents"]["behaviors"]:
                if (package_behavior["path"] == "."):
                    behavior_name = package["uuid"]
                    name_en = package["elems"]["names"].get("en_US", "")
                    name_fr = package["elems"]["names"].get("fr_FR", name_en)
                    description_en = package["elems"]["descriptions"].get("en_US", "")
                else:
                    behavior_name = package["uuid"] + "/" + package_behavior["path"]
                    name_en = package_behavior["langToName"].get("en_US", "")
                    name_fr = package_behavior["langToName"].get("fr_FR", name_en)
                    description_en = package_behavior["langToDesc"].get("en_US", "")

                tags = package_behavior["langToTags"].get("en_US", list[str]())

                behavior = NaoBehavior(
                    package_uuid = package["uuid"],
                    behavior_path = package_behavior["path"],
                    behavior_name = behavior_name,
                    localized_name = LocalizedString(en_US = name_en, fr_FR = name_fr),
                    description = description_en,
                    tags = tags
                )
                behavior_list.append(behavior)
        return behavior_list

    def _retrieve_dance_behaviors(self, behaviors: list[NaoBehavior]) -> dict[str, BehaviorInfos]:
        dances = dict[str, BehaviorInfos]()
        for behavior in behaviors:
            if ("dance" in behavior.description):
                dance = BehaviorInfos(
                    id = behavior.behavior_name,
                    behavior_name=behavior.behavior_name,
                    localized_name=behavior.localized_name,
                    description=behavior.description
                )
                dances[dance.id] = dance
        return dances

    def _retrieve_reactions_for_tag(self, behaviors: list[NaoBehavior], posture: str, tag: str) -> list[BehaviorInfos]:
        reactions = list[BehaviorInfos]()
        for behavior in behaviors:
            if (behavior.package_uuid == "animations" and
                behavior.behavior_path.startswith(posture + "/Emotions") and
                tag in behavior.tags):
                reactions.append(BehaviorInfos(
                    id = behavior.behavior_name,
                    behavior_name=behavior.behavior_name,
                    localized_name=behavior.localized_name,
                    description=behavior.description
                ))
        return reactions

    def _retrieve_reactions_for_head_touched(self, behaviors: list[NaoBehavior]) -> list[BehaviorInfos]:
        reactions = list[BehaviorInfos]()
        for behavior in behaviors:
            if (behavior.package_uuid == "dialog_touch" and
                behavior.behavior_path == "animations/head_touched"):
                reactions.append(BehaviorInfos(
                    id = behavior.behavior_name,
                    behavior_name=behavior.behavior_name,
                    localized_name=behavior.localized_name,
                    description=behavior.description
                ))
        return reactions

    def _retrieve_body_actions(self, behaviors: list[NaoBehavior]) -> dict[str, BehaviorInfos]:
        replacements = {
            'LArm': 'left arm',
            'RArm': 'right arm',
            'BothArms': 'both arms',
            'Up': 'Raise ',
            'Stretch': 'Stretch '
        }

        actions = dict[str, BehaviorInfos]()
        for behavior in behaviors:
            if (behavior.package_uuid == "dialog_move_arms"):
                # Extract name from path
                name = behavior.behavior_path.split('/')[-1]
                description = name
                # Build description using replacements
                for key, value in replacements.items():
                    if key in description:
                        description = description.replace(key, value)

                behavior.localized_name = LocalizedString(en_US = description, fr_FR="")
                behavior.description = description

                action = BehaviorInfos(
                    id = name,
                    behavior_name=behavior.behavior_name,
                    localized_name=behavior.localized_name,
                    description=behavior.description
                )
                actions[action.id] = action
        return actions

    def _retrieve_app_behaviors(self, behaviors: list[NaoBehavior]) -> dict[str, BehaviorInfos]:
        excluded_uuids = {"animations", "boot-config", "daps", "default_launchpad_plugins", "fall-recovery"}
        apps = dict[str, BehaviorInfos]()
        for behavior in behaviors:
            uuid = behavior.package_uuid
            if uuid in excluded_uuids:
                continue
            if "dialog" in uuid:
                continue
            if "dance" in behavior.description:
                continue
            if behavior.behavior_path != ".":
                continue
            app = BehaviorInfos(
                id=behavior.behavior_name,
                behavior_name=behavior.behavior_name,
                localized_name=behavior.localized_name,
                description=behavior.description
            )
            apps[app.id] = app
        return apps

    #region Fake behavior lists
    def _get_fake_dance_behaviors(self) -> dict[str, BehaviorInfos]:
        dances = dict[str, BehaviorInfos]()
        dances["caravan-palace-se"] = BehaviorInfos(
            id = "caravan-palace-se",
            behavior_name="caravan-palace-se",
            localized_name=LocalizedString(en_US="Electro Swing",
                                               fr_FR="Electro Swing"),
            description="Nao dances on Electro Swing music.\n\nThe song 'Little Lily Swing' by Tri-Tachyon is licensed under a Attribution License.You can find it here: http://freemusicarchive.org/music/Tri-Tachyon/Little_Lily_Swing/")
        dances["eagle-dance"] = BehaviorInfos(
            id = "eagle-dance",
                behavior_name="eagle-dance",
                localized_name=LocalizedString(en_US="Eagle Dance",
                                               fr_FR="La danse de l'aigle"),
            description="This is a slow dance with impressive moves balanced on one foot.\r\n")
        dances["gangnam-style"] = BehaviorInfos(
            id = "gangnam-style",
            behavior_name="gangnam-style",
            localized_name=LocalizedString(en_US="Gangnam Style",
                                            fr_FR="Gangnam sta ile"),
            description="Gangnam style dance.")
        dances["thriller-dance"] = BehaviorInfos(
            id = "thriller-dance",
            behavior_name="thriller-dance",
            localized_name=LocalizedString(en_US="The thriller dance",
                                           fr_FR="La danse thriller"),
            description="Nao dances on Michael Jackson's thriller.")
        return dances

    def _get_fake_reaction_behaviors(self) -> dict[str, list[BehaviorInfos]]:
        reactions = dict[str, list[BehaviorInfos]]()
        reactions["Happy"] = list[BehaviorInfos]()
        reactions["Proud"] = list[BehaviorInfos]()
        reactions["Laugh"] = list[BehaviorInfos]()
        reactions["Sad"] = list[BehaviorInfos]()
        reactions["HeadTouched"] = list[BehaviorInfos]()
        return reactions

    def _get_fake_body_action_behaviors(self) -> dict[str, BehaviorInfos]:
        reactions = dict[str, BehaviorInfos]()
        reactions["StretchBothArms"] = BehaviorInfos(
            id = "StretchBothArms",
            behavior_name="dialog_move_arms/animations/StretchBothArms",
            localized_name=LocalizedString(en_US="Stretch both arms",
                                           fr_FR="Etire les deux bras"),
            description="Stretch both arms")
        reactions["StretchLArm"] = BehaviorInfos(
            id = "StretchLArm",
            behavior_name="dialog_move_arms/animations/StretchLArm",
            localized_name=LocalizedString(en_US="Stretch left arm",
                                           fr_FR="Etire le bras gauche"),
            description="Stretch left arm")
        reactions["StretchRArm"] = BehaviorInfos(
            id = "StretchRArm",
            behavior_name="dialog_move_arms/animations/StretchRArm",
            localized_name=LocalizedString(en_US="Stretch right arm",
                                           fr_FR="Etire le bras droit"),
            description="Stretch right arm")
        reactions["UpBothArms"] = BehaviorInfos(
            id = "UpBothArms",
            behavior_name="dialog_move_arms/animations/UpBothArms",
            localized_name=LocalizedString(en_US="Raise both arms",
                                           fr_FR="Lève les deux bras"),
            description="Raise both arms")
        reactions["UpLArm"] = BehaviorInfos(
            id = "UpLArm",
            behavior_name="dialog_move_arms/animations/UpLArm",
            localized_name=LocalizedString(en_US="Raise left arm",
                                           fr_FR="Lève le bras gauche"),
            description="Raise left arm")
        reactions["UpRArm"] = BehaviorInfos(
            id = "UpRArm",
            behavior_name="dialog_move_arms/animations/UpRArm",
            localized_name=LocalizedString(en_US="Raise right arm",
                                           fr_FR="Lève le bras droit"),
            description="Raise right arm")
        return reactions

    def _get_fake_app_behaviors(self) -> dict[str, BehaviorInfos]:
        apps = dict[str, BehaviorInfos]()
        apps["follow-me"] = BehaviorInfos(
            id="follow-me",
            behavior_name="follow-me",
            localized_name=LocalizedString(en_US="Follow me", fr_FR="Suis moi"),
            description="Nao gives you its hand and walks with you. He will walk as long as its arm is raised, forward or backward according to the position of the arm. \n\nIf you have the arm at the vertical, and try to move it to the left or right, Nao will do sidesteps in the given direction.")
        apps["presentation"] = BehaviorInfos(
            id="presentation",
            behavior_name="presentation",
            localized_name=LocalizedString(en_US="Presentation", fr_FR="Présentation"),
            description="ao speaks about itself and what it can be used for.")
        apps["soccer-demonstration"] = BehaviorInfos(
            id="soccer-demonstration",
            behavior_name="soccer-demonstration",
            localized_name=LocalizedString(en_US="Soccer Demonstration", fr_FR="Démo de foot"),
            description="Simple soccer behavior. Nao asks the user for a red ball, takes it and throws it in front of him. After that, he tracks the ball, walks near it and shoots. He continues while he sees the ball or the user gives a tap on his head.")
        apps["walktotheball"] = BehaviorInfos(
            id="walktotheball",
            behavior_name="walktotheball",
            localized_name=LocalizedString(en_US="Walk to the ball", fr_FR="Marche vers la balle"),
            description="Take a red ball in your hand and show it to Nao. If he is far, he will try to come towards the ball. If too close, he will walk backward.")
        return apps
    #endregion

    #endregion


    #region Modules API
    async def set_tts_language(self, language: str) -> bool:
        """Set the text-to-speech language.
        
        Args:
            language: The language to set (e.g., 'English', 'French')
            
        Returns:
            bool: True if successful, False otherwise
            
        Raises:
            ValueError: If language is not supported
        """
        logger.debug("Setting TTS language to %s", language)
        
        should_return, result = self._check_connection_for_return("set_tts_language")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.tts.setLanguage, language)
            logger.info("Successfully set TTS language to %s", language)
            return True
        except Exception as e:
            logger.error("Failed to set TTS language: %s", e)
            return False

    async def say(self, text: str) -> bool:
        """Make the robot say something.
        
        Args:
            text: The text to say
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Saying: %s", text)
        
        should_return, result = self._check_connection_for_return("say")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.animated_speech.say, text)
            logger.info("Successfully said: %s", text)
            return True
        except Exception as e:
            logger.error("Failed to say text: %s", e)
            return False

    async def stop_say(self) -> bool:
        """Stop the robot talking.

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Stopping robot say")

        should_return, result = self._check_connection_for_return("stop_say")
        if should_return:
            return result

        try:
            await asyncio.to_thread(self.tts.stopAll)
            logger.info("Successfully stopped robot say")
            return True
        except Exception as e:
            logger.error("Failed to stop robot say: %s", e)
            return False

    async def wake_up(self) -> bool:
        """Enable robot motors for action.
        
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Waking up robot")
        
        should_return, result = self._check_connection_for_return("wake_up")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.motion.wakeUp)
            logger.info("Robot successfully woke up")
            return True
        except Exception as e:
            logger.error("Failed to wake up robot: %s", e)
            return False

    async def rest(self) -> bool:
        """Disable robot motors.
        
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Putting robot to rest")
        
        should_return, result = self._check_connection_for_return("rest")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.motion.rest)
            logger.info("Robot successfully put to rest")
            return True
        except Exception as e:
            logger.error("Failed to put robot to rest: %s", e)
            return False

    async def stand_up(self) -> bool:
        """Make the robot stand up.
        
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Making robot stand up")
        
        should_return, result = self._check_connection_for_return("stand_up")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.robot_posture.setMaxTryNumber, self.POSTURE_MAX_TRIES)
            result = await asyncio.to_thread(self.robot_posture.goToPosture, "Stand", self.POSTURE_SPEED)
            if result:
                logger.info("Robot successfully stood up")
            else:
                logger.warning("Robot failed to stand up")
            return result
        except Exception as e:
            logger.error("Failed to make robot stand up: %s", e)
            return False

    async def sit_down(self) -> bool:
        """Make the robot sit down.
        
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Making robot sit down")

        should_return, result = self._check_connection_for_return("sit_down")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.robot_posture.setMaxTryNumber, self.POSTURE_MAX_TRIES)
            result = await asyncio.to_thread(self.robot_posture.goToPosture, "Sit", self.POSTURE_SPEED)
            if result:
                logger.info("Robot successfully sat down")
            else:
                logger.warning("Robot failed to sit down")
            return result
        except Exception as e:
            logger.error("Failed to make robot sit down: %s", e)
            return False

    async def change_eyes_color(self, color: str) -> bool:
        """Change the color of the robot's eyes.

        Args:
            color: The color to set (among 'white', 'red', 'green', 'blue', 'yellow', 'magenta', 'cyan')

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Changing eyes color to %s", color)

        should_return, result = self._check_connection_for_return("change_eyes_color")
        if should_return:
            return result

        try:
            await asyncio.to_thread(self.leds.fadeRGB, "FaceLeds", color, 0)
            logger.info("Successfully changed eyes color to %s", color)
            return True
        except Exception as e:
            logger.error("Failed to change eyes color: %s", e)
            return False

    async def set_basic_awareness_state(self, enabled: bool, engagement_mode: str, tracking_mode: str) -> bool:
        """Set the basic awareness state of the robot.
        
        Args:
            enabled: Whether to enable basic awareness
            engagement_mode: The engagement mode to use
            tracking_mode: The tracking mode to use
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Setting basic awareness state: enabled=%s, engagement_mode=%s, tracking_mode=%s",
                    enabled, engagement_mode, tracking_mode)
        
        should_return, result = self._check_connection_for_return("set_basic_awareness_state")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.basic_awareness.setEngagementMode, engagement_mode)
            await asyncio.to_thread(self.basic_awareness.setTrackingMode, tracking_mode)
            if enabled:
                await asyncio.to_thread(self.basic_awareness.startAwareness)
                logger.info("Basic awareness enabled")
            else:
                await asyncio.to_thread(self.basic_awareness.stopAwareness)
                logger.info("Basic awareness disabled")
            return True
        except Exception as e:
            logger.error("Failed to set basic awareness state: %s", e)
            return False

    async def set_breathing_enabled(self, enabled: bool, chain_name: str) -> bool:
        """Enable or disable breathing for a specific chain.
        
        Args:
            enabled: Whether to enable breathing
            chain_name: The name of the chain to control
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Setting breathing state: enabled=%s, chain_name=%s", enabled, chain_name)
        
        should_return, result = self._check_connection_for_return("set_breathing_enabled")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.motion.setBreathEnabled, chain_name, enabled)
            logger.info("Successfully set breathing state for chain %s to %s", chain_name, enabled)
            return True
        except Exception as e:
            logger.error("Failed to set breathing state: %s", e)
            return False

    async def run_behavior(self, behavior_name: str) -> bool:
        """Run a specific behavior.
        
        Args:
            behavior_name: The name of the behavior to run
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Running behavior: %s", behavior_name)
        
        should_return, result = self._check_connection_for_return("run_behavior")
        if should_return:
            return result
        
        try:
            self.current_behaviors.append(behavior_name)
            logger.info("Starting behavior: %s", behavior_name)
            await asyncio.to_thread(self.behavior_manager.runBehavior, behavior_name)
            logger.info("Ended behavior: %s", behavior_name)
            if behavior_name in self.current_behaviors:
                self.current_behaviors.remove(behavior_name)
            return True
        except Exception as e:
            logger.error("Failed to run behavior: %s", e)
            return False

    async def stop_behavior(self, behavior_name: str) -> bool:
        """Stop a running behavior.
        
        Args:
            behavior_name: The name of the behavior to stop
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Stopping behavior: %s", behavior_name)
        
        should_return, result = self._check_connection_for_return("stop_behavior")
        if should_return:
            return result
        
        try:
            await asyncio.to_thread(self.behavior_manager.stopBehavior, behavior_name)
            logger.info("Successfully stopped behavior: %s", behavior_name)
            if behavior_name in self.current_behaviors:
                self.current_behaviors.remove(behavior_name)
            return True
        except Exception as e:
            logger.error("Failed to stop behavior: %s", e)
            return False

    def get_dance_behaviors(self) -> list[BehaviorInfos]:
        """Get the dance behaviors.

        Returns:
            list[BehaviorInfos]: The dance behaviors
        """
        return list(self._dance_behaviors.values())

    async def dance(self, dance_id: str) -> bool:
        """Make the robot dance.

        Args:
            dance_id: The id of the dance to run

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Dancing for id: %s", dance_id)

        if (dance_id not in self._dance_behaviors):
            logger.error("Dance with id '%s' not found", dance_id)
            return False

        should_return, result = self._check_connection_for_return("dance")
        if should_return:
            return result

        self.current_dances.append(dance_id)
        result = await self.run_behavior(self._dance_behaviors[dance_id].behavior_name)
        if dance_id in self.current_dances:
            self.current_dances.remove(dance_id)
        return result

    async def stop_dance(self, dance_id: str) -> bool:
        """Stop the robot from dancing.

        Args:
            dance_id: The id of the dance to stop

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Stopping dance for id: %s", dance_id)

        if (dance_id not in self._dance_behaviors):
            logger.error("Dance with id '%s' not found", dance_id)
            return False

        should_return, result = self._check_connection_for_return("stop_dance")
        if should_return:
            return result

        if (dance_id not in self.current_dances):
            logger.error("Dance with id '%s' not found in current dances", dance_id)
            return False

        result = await self.stop_behavior(self._dance_behaviors[dance_id].behavior_name)
        if dance_id in self.current_dances:
            self.current_dances.remove(dance_id)
        return result

    def get_expressive_reaction_types(self) -> list[str]:
        """Get the expressive reaction types.

        Returns:
            list[str]: The expressive reaction types
        """
        return list(self._expressive_reaction_behaviors.keys())

    async def expressive_reaction(self, reaction_type: str) -> bool:
        """Make the robot react to a specific emotion/situation.

        Args:
            reaction_type: The type of reaction to make

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Reacting: %s", reaction_type)

        if (reaction_type not in self._expressive_reaction_behaviors):
            logger.error("Reaction type '%s' not found", reaction_type)
            return False

        should_return, result = self._check_connection_for_return("expressive_reaction")
        if should_return:
            return result

        reaction_behaviors = self._expressive_reaction_behaviors[reaction_type]
        if (len(reaction_behaviors) == 0):
            logger.error("No reaction behaviors found for reaction type '%s'", reaction_type)
            return False

        random_reaction = random.choice(reaction_behaviors)
        self.current_expressive_reactions[reaction_type] = random_reaction.behavior_name
        result = await self.run_behavior(random_reaction.behavior_name)
        if reaction_type in self.current_expressive_reactions:
            del self.current_expressive_reactions[reaction_type]
        return result

    async def stop_expressive_reaction(self, reaction_type: str) -> bool:
        """Stop the robot from reacting to a specific emotion/situation.

        Args:
            reaction_type: The type of reaction to stop

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Stopping reaction: %s", reaction_type)

        if (reaction_type not in self._expressive_reaction_behaviors):
            logger.error("Reaction type '%s' not found", reaction_type)
            return False

        should_return, result = self._check_connection_for_return("stop_expressive_reaction")
        if should_return:
            return result

        if (reaction_type not in self.current_expressive_reactions):
            logger.error("Reaction with type '%s' not found in current reactions", reaction_type)
            return False

        result = await self.stop_behavior(self._expressive_reaction_behaviors[reaction_type])
        if reaction_type in self.current_expressive_reactions:
            del self.current_expressive_reactions[reaction_type]
        return result

    def get_body_action_behaviors(self) -> list[BehaviorInfos]:
        """Get the body action behaviors.

        Returns:
            list[BehaviorInfos]: The body action behaviors
        """
        return list(self._body_action_behaviors.values())

    async def body_action(self, body_action_id: str) -> bool:
        """Make the robot perform a specific body action.

        Args:
            body_action_id: The id of the body action to perform

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Performing body action for id: %s", body_action_id)

        if (body_action_id not in self._body_action_behaviors):
            logger.error("Body action with id '%s' not found", body_action_id)
            return False

        should_return, result = self._check_connection_for_return("body_action")
        if should_return:
            return result

        self.current_body_actions.append(body_action_id)
        result = await self.run_behavior(self._body_action_behaviors[body_action_id].behavior_name)
        if body_action_id in self.current_body_actions:
            self.current_body_actions.remove(body_action_id)
        return result

    async def stop_body_action(self, body_action_id: str) -> bool:
        """Stop the robot from performing a specific body action.

        Args:
            body_action_id: The id of the body action to stop

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Stopping body action for id: %s", body_action_id)

        if (body_action_id not in self._body_action_behaviors):
            logger.error("Body action with id '%s' not found", body_action_id)
            return False

        should_return, result = self._check_connection_for_return("stop_body_action")
        if should_return:
            return result

        if (body_action_id not in self.current_body_actions):
            logger.error("Body action with id '%s' not found in current body actions", body_action_id)
            return False

        result = await self.stop_behavior(self._body_action_behaviors[body_action_id].behavior_name)
        if body_action_id in self.current_body_actions:
            self.current_body_actions.remove(body_action_id)
        return result

    def get_app_behaviors(self) -> list[BehaviorInfos]:
        """Get the app behaviors.

        Returns:
            list[BehaviorInfos]: The app behaviors
        """
        return list(self._app_behaviors.values())

    async def run_app(self, app_id: str) -> bool:
        """Run a specific app behavior.

        Args:
            app_id: The id of the app to run

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Running app for id: %s", app_id)

        if (app_id not in self._app_behaviors):
            logger.error("App with id '%s' not found", app_id)
            return False

        should_return, result = self._check_connection_for_return("run_app")
        if should_return:
            return result

        self.current_apps.append(app_id)
        result = await self.run_behavior(self._app_behaviors[app_id].behavior_name)
        if app_id in self.current_apps:
            self.current_apps.remove(app_id)
        return result

    async def stop_app(self, app_id: str) -> bool:
        """Stop a running app behavior.

        Args:
            app_id: The id of the app to stop

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug("Stopping app for id: %s", app_id)

        if (app_id not in self._app_behaviors):
            logger.error("App with id '%s' not found", app_id)
            return False

        should_return, result = self._check_connection_for_return("stop_app")
        if should_return:
            return result

        if (app_id not in self.current_apps):
            logger.error("App with id '%s' not found in current apps", app_id)
            return False

        result = await self.stop_behavior(self._app_behaviors[app_id].behavior_name)
        if app_id in self.current_apps:
            self.current_apps.remove(app_id)
        return result
    #endregion
