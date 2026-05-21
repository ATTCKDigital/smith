class Animal:
    """An animal."""

    def __init__(self, name: str):
        self.name = name

    def speak(self) -> str:
        return "..."


class Dog(Animal):
    def speak(self) -> str:
        return "woof"

    def fetch(self, item: str):
        return f"got {item}"


class Empty:
    pass
