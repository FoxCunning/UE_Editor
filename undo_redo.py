__author__ = "Fox Cunning"
# noinspection SpellCheckingInspection
__credits__ = ["jcuster", "Fox Cunning"]

from typing import Tuple, List

# Default value for maximum number of actions in the undo stack
_MAX_UNDO = 8192


class UndoRedo:

    # ------------------------------------------------------------------------------------------------------------------

    class UndoRedoAction:
        def __init__(self, do_func: callable, do_args: Tuple, undo_args: Tuple, undo_func: callable = None, **kwargs):
            self.do_func = do_func
            self.undo_func = undo_func if undo_func is not None else do_func

            self.do_args = do_args
            self.undo_args = undo_args

            self._last_done = False

            self.text = kwargs.get("text", "")

        def __call__(self):
            self._last_done = not self._last_done

            if not self._last_done:
                return self.undo_func(*self.undo_args)
            else:
                return self.do_func(*self.do_args)

    # ------------------------------------------------------------------------------------------------------------------

    def __init__(self, max_undo: int = _MAX_UNDO):
        self._undo_buf: List[UndoRedo.UndoRedoAction] = []
        self._redo_buf: List[UndoRedo.UndoRedoAction] = []
        self._max_undo = max_undo

    # ------------------------------------------------------------------------------------------------------------------

    def __call__(self, do_func: callable, do_args: Tuple, undo_args: Tuple, undo_func: callable = None, **kwargs):
        # Create undoable action
        action = UndoRedo.UndoRedoAction(do_func, do_args, undo_args, undo_func, **kwargs)

        # Add it to our undo stack
        self._undo_buf.append(action)
        # ...and clear the redo stack (this will only be filled when something has just been undone)
        self._redo_buf = []

        # If there are too many actions in the undo stack, eliminate the bottom ones
        while len(self._undo_buf) > self._max_undo:
            self._undo_buf.pop(0)

        # Perform the action
        return action()

    # ------------------------------------------------------------------------------------------------------------------

    def can_undo(self, count: int = 1) -> bool:
        """
        Parameters
        ----------
        count: int
            Number of desired undo actions
        Returns
        -------
        bool
            True if the given number of actions can be undone, False otherwise.
        """
        return len(self._undo_buf) >= count

    # ------------------------------------------------------------------------------------------------------------------

    def can_redo(self, count: int = 1) -> bool:
        """
        Parameters
        ----------
        count: int
            Number of desired redo actions

        Returns
        -------
        bool
            True if the given number of actions can be redone, False otherwise.
        """
        return len(self._redo_buf) >= count

    # ------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _perform_actions(actions: List[UndoRedoAction]) -> List:
        """
        Internal method to perform actions from a list.

        Parameters
        ----------
        actions: List[UndoRedoAction]
            The list of actions to be performed.

        Returns
        -------
        List:
            A list of results for each performed action.
        """
        results = [a() for a in reversed(actions)]

        return results

    # ------------------------------------------------------------------------------------------------------------------

    def undo(self, count: int = 1) -> List:
        if not self.can_undo(count):
            raise ValueError(f"Can't undo {count} actions.")

        first = len(self._undo_buf) - count
        actions = self._undo_buf[first:]
        # Pop the requested actions out of the undo stack...
        self._undo_buf = self._undo_buf[:first]
        # ...and push them onto the redo stack
        self._redo_buf += actions
        # Perform actions
        return UndoRedo._perform_actions(actions)

    # ------------------------------------------------------------------------------------------------------------------

    def redo(self, count: int = 1) -> List:
        if not self.can_redo(count):
            raise ValueError(f"Can't redo {count} actions.")

        first = len(self._redo_buf) - count
        actions = self._redo_buf[first:]
        self._redo_buf = self._redo_buf[:first]
        self._undo_buf += actions

        actions.reverse()
        return UndoRedo._perform_actions(actions)

    # ------------------------------------------------------------------------------------------------------------------

    def clear(self):
        self._undo_buf = []
        self._redo_buf = []

    # ------------------------------------------------------------------------------------------------------------------

    def undo_count(self) -> int:
        return len(self._undo_buf)

    # ------------------------------------------------------------------------------------------------------------------

    def redo_count(self) -> int:
        return len(self._redo_buf)

    # ------------------------------------------------------------------------------------------------------------------

    def get_undo_text(self, index: int = None) -> str:
        size = len(self._undo_buf)
        if size < 1:
            return "Nothing to Undo"

        if index is None:
            index = size - 1

        return self._undo_buf[index].text

    # ------------------------------------------------------------------------------------------------------------------

    def get_redo_text(self, index: int = None) -> str:
        size = len(self._redo_buf)
        if size < 1:
            return "Nothing to Redo"

        if index is None:
            index = size - 1

        return self._redo_buf[index].text
