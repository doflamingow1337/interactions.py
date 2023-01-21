import uuid
from abc import abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Sequence, TYPE_CHECKING, Union

import attrs
import discord_typings

from interactions.client.const import (
    SELECTS_MAX_OPTIONS,
    SELECT_MAX_NAME_LENGTH,
    ACTION_ROW_MAX_ITEMS,
    MISSING,
)
from interactions.client.mixins.serialization import DictSerializationMixin
from interactions.client.utils import list_converter
from interactions.client.utils.attr_utils import str_validator
from interactions.client.utils.serializer import export_converter
from interactions.models.discord.emoji import process_emoji
from interactions.models.discord.enums import ButtonStyles, ComponentTypes, ChannelTypes

if TYPE_CHECKING:
    from interactions.models.discord.emoji import PartialEmoji


class BaseComponent(DictSerializationMixin):
    """
    A base component class.

    !!! Warning
        This should never be directly instantiated.

    """

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict) -> "BaseComponent":
        """
        Create a component from a dictionary.

        Args:
            data: the dictionary to create the component from

        Returns:
            The created component.

        """
        raise NotImplementedError

    @classmethod
    def from_dict_factory(
        cls,
        data: dict,
        *,
        alternate_mapping: dict[ComponentTypes, "BaseComponent"] | None = None,
    ) -> "BaseComponent":
        """
        Creates a component from a payload.

        Args:
            data: the payload from Discord
            alternate_mapping: an optional mapping of component types to classes
        """
        data.pop("hash", None)  # redundant

        component_type = data.pop("type", None)

        mapping = alternate_mapping or TYPE_COMPONENT_MAPPING

        component_class = mapping.get(component_type, None)
        if not component_class:
            raise TypeError(
                f"Unsupported component type for {data} ({component_type}), please consult the docs."
            )

        return component_class.from_dict(data)


class InteractiveComponent(BaseComponent):
    """
    A base interactive component class.

    !!! Warning
        This should never be instantiated.

    """

    type: ComponentTypes
    custom_id: str

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, dict):
            other = BaseComponent.from_dict_factory(other)
        return self.custom_id == other.custom_id and self.type == other.type


class ActionRow(BaseComponent):
    """
    Represents an action row.

    Attributes:
        components list[Dict | BaseComponent]: A sequence of components contained within this action row
    """

    def __init__(self, *components: Dict | BaseComponent) -> None:
        if isinstance(components, (list, tuple)):
            # flatten user error
            components = [c for c in components]

        self.components: list[Dict | BaseComponent] = [
            BaseComponent.from_dict_factory(c) if isinstance(c, dict) else c
            for c in components
        ]

        self.type: ComponentTypes = ComponentTypes.ACTION_ROW
        self._max_items = ACTION_ROW_MAX_ITEMS

    @classmethod
    def from_dict(cls, data: discord_typings.ActionRowData) -> "ActionRow":
        return cls(*data["components"])

    def add_component(self, *components: dict | BaseComponent) -> None:
        """
        Add a component to this action row.

        Args:
            *components: The component(s) to add.
        """
        if isinstance(components, (list, tuple)):
            # flatten user error
            components = [c for c in components]

        self.components.extend(
            BaseComponent.from_dict_factory(c) if isinstance(c, dict) else c
            for c in components
        )

    @classmethod
    def split_components(
        cls, *components: dict | BaseComponent, count_per_row: int = 5
    ) -> list["ActionRow"]:
        """
        Split components into action rows.

        Args:
            *components: The components to split.
            count_per_row: The amount of components to have per row.

        Returns:
            A list of action rows.
        """
        buffer = []
        action_rows = []

        for component in components:
            c_type = component.type if hasattr(component, "type") else component["type"]
            if c_type in (
                ComponentTypes.STRING_SELECT,
                ComponentTypes.USER_SELECT,
                ComponentTypes.ROLE_SELECT,
                ComponentTypes.MENTIONABLE_SELECT,
                ComponentTypes.CHANNEL_SELECT,
            ):
                # Selects can only be in their own row
                if buffer:
                    action_rows.append(cls(*buffer))
                    buffer = []
                action_rows.append(cls(component))
            else:
                buffer.append(component)
                if len(buffer) >= count_per_row:
                    action_rows.append(cls(*buffer))
                    buffer = []

        if buffer:
            action_rows.append(cls(*buffer))
        return action_rows

    def to_dict(self) -> discord_typings.ActionRowData:
        return {
            "type": self.type.value,  # type: ignore
            "components": [c.to_dict() for c in self.components],
        }


class Button(InteractiveComponent):
    """
    Represents a discord ui button.

    Attributes:
        style optional[ButtonStyles, int]: Buttons come in a variety of styles to convey different types of actions.
        label optional[str]: The text that appears on the button, max 80 characters.
        emoji optional[Union[PartialEmoji, dict, str]]: The emoji that appears on the button.
        custom_id Optional[str]: A developer-defined identifier for the button, max 100 characters.
        url Optional[str]: A url for link-style buttons.
        disabled bool: Disable the button and make it not interactable, default false.

    """

    def __init__(
        self,
        *,
        style: ButtonStyles,
        label: str | None,
        emoji: "PartialEmoji | None" = None,
        custom_id: str = None,
        url: str | None = None,
        disabled: bool = False,
    ):
        self.style: ButtonStyles = style
        self.label: str | None = label
        self.emoji: "PartialEmoji | None" = emoji
        self.custom_id: str | None = custom_id
        self.url: str | None = url
        self.disabled: bool = disabled

        self.type: ComponentTypes = ComponentTypes.BUTTON

        if self.style != ButtonStyles.URL:
            # automatically set the custom_id if it's not a URL button, and it's not already set
            if self.custom_id is None:
                self.custom_id = str(uuid.uuid4())
        else:
            if self.custom_id is not None:
                raise ValueError("URL buttons cannot have a custom_id.")
            if self.url is None:
                raise ValueError("URL buttons must have a url.")

        if not self.label and not self.emoji:
            raise ValueError("Buttons must have a label or an emoji.")

    @classmethod
    def from_dict(cls, data: discord_typings.ButtonComponentData) -> "Button":
        return cls(
            style=ButtonStyles(data["style"]),
            label=data.get("label"),
            emoji=process_emoji(data.get("emoji")),
            custom_id=data.get("custom_id"),
            url=data.get("url"),
            disabled=data.get("disabled", False),
        )

    def to_dict(self) -> discord_typings.ButtonComponentData:
        return {
            "type": self.type.value,  # type: ignore
            "style": self.style.value,  # type: ignore
            "label": self.label,
            "emoji": self.emoji.to_dict() if self.emoji else None,
            "custom_id": self.custom_id,
            "url": self.url,
            "disabled": self.disabled,
        }


class BaseSelectMenu(InteractiveComponent):
    """
    Represents a select menu component

    Attributes:
        custom_id str: A developer-defined identifier for the button, max 100 characters.
        placeholder str: The custom placeholder text to show if nothing is selected, max 100 characters.
        min_values Optional[int]: The minimum number of items that must be chosen. (default 1, min 0, max 25)
        max_values Optional[int]: The maximum number of items that can be chosen. (default 1, max 25)
        disabled bool: Disable the select and make it not intractable, default false.
        type Union[ComponentTypes, int]: The action role type number defined by discord. This cannot be modified.
    """

    def __init__(
        self,
        *,
        placeholder: str | None = None,
        min_values: int = 1,
        max_values: int = 1,
        custom_id: str | None = None,
        disabled: bool = False,
    ):
        self.custom_id: str = custom_id or str(uuid.uuid4())
        self.placeholder: str | None = placeholder
        self.min_values: int = min_values
        self.max_values: int = max_values
        self.disabled: bool = disabled

        self.type: ComponentTypes = MISSING

    @classmethod
    def from_dict(
        cls, data: discord_typings.SelectMenuComponentData
    ) -> "BaseSelectMenu":
        return cls(
            placeholder=data.get("placeholder"),
            min_values=data["min_values"],
            max_values=data["max_values"],
            custom_id=data["custom_id"],
            disabled=data.get("disabled", False),
        )

    def to_dict(self) -> discord_typings.SelectMenuComponentData:
        return {
            "type": self.type.value,  # type: ignore
            "custom_id": self.custom_id,
            "placeholder": self.placeholder,
            "min_values": self.min_values,
            "max_values": self.max_values,
            "disabled": self.disabled,
        }


class StringSelectOption(BaseComponent):
    """
    Represents a select option.

    Attributes:
        label str: The label (max 80 characters)
        value str: The value of the select, this is whats sent to your bot
        description Optional[str]: A description of this option
        emoji Optional[Union[PartialEmoji, dict, str]: An emoji to show in this select option
        default bool: Is this option selected by default
    """

    def __init__(
        self,
        *,
        label: str,
        value: str,
        description: str | None = None,
        emoji: "PartialEmoji | None" = None,
        default: bool = False,
    ):
        self.label: str = label
        self.value: str = value
        self.description: str | None = description
        self.emoji: PartialEmoji | None = emoji
        self.default: bool = default

    @classmethod
    def converter(cls, value: Any) -> "StringSelectOption":
        if isinstance(value, StringSelectOption):
            return value
        if isinstance(value, dict):
            return cls.from_dict(value)

        if isinstance(value, str):
            return cls(label=value, value=value)

        try:
            possible_iter = iter(value)

            return cls(label=possible_iter[0], value=possible_iter[1])
        except TypeError:
            pass

        raise TypeError(
            f"Cannot convert {value} of type {type(value)} to a SelectOption"
        )

    @classmethod
    def from_dict(
        cls, data: discord_typings.SelectMenuOptionData
    ) -> "StringSelectOption":
        return cls(
            label=data["label"],
            value=data["value"],
            description=data.get("description"),
            emoji=process_emoji(data.get("emoji")),
            default=data.get("default", False),
        )

    def to_dict(self) -> discord_typings.SelectMenuOptionData:
        return {
            "label": self.label,
            "value": self.value,
            "description": self.description,
            "emoji": self.emoji.to_dict() if self.emoji else None,
            "default": self.default,
        }


class StringSelectMenu(BaseSelectMenu):
    """
    Represents a string select component.

    Attributes:
        options List[dict]: The choices in the select, max 25.
        custom_id str: A developer-defined identifier for the button, max 100 characters.
        placeholder str: The custom placeholder text to show if nothing is selected, max 100 characters.
        min_values Optional[int]: The minimum number of items that must be chosen. (default 1, min 0, max 25)
        max_values Optional[int]: The maximum number of items that can be chosen. (default 1, max 25)
        disabled bool: Disable the select and make it not intractable, default false.
        type Union[ComponentTypes, int]: The action role type number defined by discord. This cannot be modified.
    """

    def __init__(
        self,
        *options: StringSelectOption | str | discord_typings.SelectMenuOptionData,
        placeholder: str | None = None,
        min_values: int = 1,
        max_values: int = 1,
        custom_id: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            custom_id=custom_id,
            disabled=disabled,
        )
        self.options: list[StringSelectOption] = [
            StringSelectOption.converter(option) for option in options
        ]
        self.type: ComponentTypes = ComponentTypes.STRING_SELECT

    @classmethod
    def from_dict(
        cls, data: discord_typings.SelectMenuComponentData
    ) -> "StringSelectMenu":
        return cls(
            *data["options"],
            placeholder=data.get("placeholder"),
            min_values=data["min_values"],
            max_values=data["max_values"],
            custom_id=data["custom_id"],
            disabled=data.get("disabled", False),
        )

    def to_dict(self) -> discord_typings.SelectMenuComponentData:
        return {
            **super().to_dict(),
            "options": [option.to_dict() for option in self.options],
        }

class UserSelectMenu(BaseSelectMenu):
    """
    Represents a user select component.

    Attributes:
        custom_id str: A developer-defined identifier for the button, max 100 characters.
        placeholder str: The custom placeholder text to show if nothing is selected, max 100 characters.
        min_values Optional[int]: The minimum number of items that must be chosen. (default 1, min 0, max 25)
        max_values Optional[int]: The maximum number of items that can be chosen. (default 1, max 25)
        disabled bool: Disable the select and make it not intractable, default false.
        type Union[ComponentTypes, int]: The action role type number defined by discord. This cannot be modified.
    """

    def __init__(
        self,
        *,
        placeholder: str | None = None,
        min_values: int = 1,
        max_values: int = 1,
        custom_id: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            custom_id=custom_id,
            disabled=disabled,
        )

        self.type: ComponentTypes = ComponentTypes.USER_SELECT


class RoleSelectMenu(BaseSelectMenu):
    """
    Represents a user select component.

    Attributes:
        custom_id str: A developer-defined identifier for the button, max 100 characters.
        placeholder str: The custom placeholder text to show if nothing is selected, max 100 characters.
        min_values Optional[int]: The minimum number of items that must be chosen. (default 1, min 0, max 25)
        max_values Optional[int]: The maximum number of items that can be chosen. (default 1, max 25)
        disabled bool: Disable the select and make it not intractable, default false.
        type Union[ComponentTypes, int]: The action role type number defined by discord. This cannot be modified.
    """

    def __init__(
        self,
        *,
        placeholder: str | None = None,
        min_values: int = 1,
        max_values: int = 1,
        custom_id: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            custom_id=custom_id,
            disabled=disabled,
        )

        self.type: ComponentTypes = ComponentTypes.ROLE_SELECT


class MentionableSelectMenu(BaseSelectMenu):
    def __init__(
        self,
        *,
        placeholder: str | None = None,
        min_values: int = 1,
        max_values: int = 1,
        custom_id: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            custom_id=custom_id,
            disabled=disabled,
        )

        self.type: ComponentTypes = ComponentTypes.MENTIONABLE_SELECT


class ChannelSelectMenu(BaseSelectMenu):
    def __init__(
        self,
        *,
        channel_types: list[ChannelTypes] | None = None,
        placeholder: str | None = None,
        min_values: int = 1,
        max_values: int = 1,
        custom_id: str | None = None,
        disabled: bool = False,
    ):
        super().__init__(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            custom_id=custom_id,
            disabled=disabled,
        )

        self.channel_types: list[ChannelTypes] | None = channel_types or []
        self.type: ComponentTypes = ComponentTypes.CHANNEL_SELECT

    @classmethod
    def from_dict(
        cls, data: discord_typings.SelectMenuComponentData
    ) -> "ChannelSelectMenu":
        return cls(
            placeholder=data.get("placeholder"),
            min_values=data["min_values"],
            max_values=data["max_values"],
            custom_id=data["custom_id"],
            disabled=data.get("disabled", False),
            channel_types=data.get("channel_types", []),
        )

    def to_dict(self) -> discord_typings.SelectMenuComponentData:
        return {
            **super().to_dict(),
            "channel_types": self.channel_types,
        }


def process_components(
    components: Optional[
        Union[
            List[List[Union[BaseComponent, Dict]]],
            List[Union[BaseComponent, Dict]],
            BaseComponent,
            Dict,
        ]
    ]
) -> List[Dict]:
    """
    Process the passed components into a format discord will understand.

    Args:
        components: List of dict / components to process

    Returns:
        formatted dictionary for discord

    Raises:
        ValueError: Invalid components

    """
    if not components:
        # Its just empty, so nothing to process.
        return components

    if isinstance(components, dict):
        # If a naked dictionary is passed, assume the user knows what they're doing and send it blindly
        # after wrapping it in a list for discord
        return [components]

    if issubclass(type(components), BaseComponent):
        # Naked component was passed
        components = [components]

    if isinstance(components, list):
        if all(isinstance(c, dict) for c in components):
            # user has passed a list of dicts, this is the correct format, blindly send it
            return components

        if all(isinstance(c, list) for c in components):
            # list of lists... actionRow-less sending
            return [ActionRow(*row).to_dict() for row in components]

        if all(issubclass(type(c), InteractiveComponent) for c in components):
            # list of naked components
            return [ActionRow(*components).to_dict()]

        if all(isinstance(c, ActionRow) for c in components):
            # we have a list of action rows
            return [action_row.to_dict() for action_row in components]

    raise ValueError(f"Invalid components: {components}")


def spread_to_rows(
    *components: Union[ActionRow, Button, StringSelectMenu], max_in_row: int = 5
) -> List[ActionRow]:
    """
    A helper function that spreads your components into `ActionRow`s of a set size.

    Args:
        *components: The components to spread, use `None` to explicit start a new row
        max_in_row: The maximum number of components in each row

    Returns:
        List[ActionRow] of components spread to rows

    Raises:
        ValueError: Too many or few components or rows

    """
    # todo: incorrect format errors
    if not components or len(components) > 25:
        raise ValueError("Number of components should be between 1 and 25.")
    if not 1 <= max_in_row <= 5:
        raise ValueError("max_in_row should be between 1 and 5.")

    rows = []
    button_row = []
    for component in list(components):
        if component is not None and component.type == ComponentTypes.BUTTON:
            button_row.append(component)

            if len(button_row) == max_in_row:
                rows.append(ActionRow(*button_row))
                button_row = []

            continue

        if button_row:
            rows.append(ActionRow(*button_row))
            button_row = []

        if component is not None:
            if component.type == ComponentTypes.ACTION_ROW:
                rows.append(component)
            elif component.type == ComponentTypes.STRING_SELECT:
                rows.append(ActionRow(component))
    if button_row:
        rows.append(ActionRow(*button_row))

    if len(rows) > 5:
        raise ValueError("Number of rows exceeds 5.")

    return rows


def get_components_ids(
    component: Union[str, dict, list, InteractiveComponent]
) -> Iterator[str]:
    """
    Creates a generator with the `custom_id` of a component or list of components.

    Args:
        component: Objects to get `custom_id`s from

    Returns:
        Generator with the `custom_id` of a component or list of components.

    Raises:
        ValueError: Unknown component type

    """
    if isinstance(component, str):
        yield component
    elif isinstance(component, dict):
        if component["type"] == ComponentTypes.actionrow:
            yield from (
                comp["custom_id"]
                for comp in component["components"]
                if "custom_id" in comp
            )
        elif "custom_id" in component:
            yield component["custom_id"]
    elif c_id := getattr(component, "custom_id", None):
        yield c_id
    elif isinstance(component, ActionRow):
        yield from (
            comp_id
            for comp in component.components
            for comp_id in get_components_ids(comp)
        )

    elif isinstance(component, list):
        yield from (
            comp_id for comp in component for comp_id in get_components_ids(comp)
        )
    else:
        raise ValueError(
            f"Unknown component type of {component} ({type(component)}). "
            f"Expected str, dict or list"
        )


TYPE_COMPONENT_MAPPING = {
    ComponentTypes.ACTION_ROW: ActionRow,
    ComponentTypes.BUTTON: Button,
    ComponentTypes.STRING_SELECT: StringSelectMenu,
    ComponentTypes.USER_SELECT: UserSelectMenu,
    ComponentTypes.CHANNEL_SELECT: ChannelSelectMenu,
    ComponentTypes.ROLE_SELECT: RoleSelectMenu,
    ComponentTypes.MENTIONABLE_SELECT: MentionableSelectMenu,
}
