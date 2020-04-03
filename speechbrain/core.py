import re
import os
import sys
import yaml
import torch
import logging
import inspect
import argparse
from speechbrain.utils.logger import setup_logging
from speechbrain.utils.data_utils import load_extended_yaml, instantiate
logger = logging.getLogger(__name__)


class Experiment:
    r'''A class for reading configuration files and creating folders

    The experiment class implements important functionality related to
    running experiments, such as setting up the experimental directories
    and loading hyperparameters. A few key parameters, listed below,
    can be set in three ways, in increasing priority order.

    1. They may be passed to the `__init__()` method for this class
    2. They may be stored in a yaml file, the name of which is
        passed to the `__init__()` method of this class.
    3. They may be passed as command-line arguments.

    Any of the keys listed in the yaml file may be overriden using
    the `overrides` parameter passed either via `__init__()` or
    via the command-line. The value of this parameter should be a
    yaml-formatted string, though a shortcut has been provided for
    nested items, e.g.

        {model.arg1: value, model.arg2.arg3: 3., model.arg2.arg4: True}

    will be interpreted as:

        {'model': {'arg1': 'value', 'arg2': {'arg3': 3., 'arg4': True}}}

    Parameters:
        yaml_stream (stream): A file-like object or string containing
            experimental parameters. The format of the file is described in
            the method `load_extended_yaml()`. The rest of the parameters to
            this function may also be specified in the command-line parameters
            or in the `constants:` section of the yaml file.
        yaml_overrides (str): A yaml-formatted string containing overrides for
            the parameters listed in the file passed to `param_filename`.
        output_folder (str): A folder to store the results of the experiment,
            as well as any checkpoints, logs, or other generated data.
        seed (int): The random seed used to ensure the experiment is
            reproducible if executed on the same device on the same machine.
        log_config (str): The name of a file specifying the parameters for
            logging, in yaml format.
        commandline_args (list): The arguments from the command-line for
            overriding the other parameters to this method

    Example:
        >>> yaml_string = """
        ... constants:
        ...     output_folder: exp
        ...     save_folder: !$ <constants.output_folder>/save
        ... """
        >>> sb = Experiment(yaml_string)
        >>> sb.constants['save_folder']
        'exp/save'

    Author:
        Peter Plantinga 2020
    '''
    def __init__(
        self,
        yaml_stream,
        yaml_overrides='',
        output_folder=None,
        seed=None,
        log_config='logging.yaml',
        commandline_args=[],
    ):
        # Initialize stored values
        self.constants = {
            'output_folder': output_folder,
            'seed': seed,
            'log_config': log_config,
        }

        # Parse yaml overrides, with command-line args taking precedence
        # over the parameters passed to this method. These overrides
        # will take precedence over the parameters listed in the file.
        overrides = parse_overrides(yaml_overrides)
        cmd_args = parse_arguments(commandline_args)
        if 'yaml_overrides' in cmd_args:
            overrides.update(parse_overrides(cmd_args['yaml_overrides']))

        # Load parameters file and store
        parameters = load_extended_yaml(yaml_stream, overrides)
        self._update_attributes(parameters)
        self._update_attributes(cmd_args)

        # Use experimental parameters to initialize experiment
        torch.manual_seed(self.constants['seed'])
        logger_overrides = {}
        if self.constants['output_folder']:
            if not os.path.isdir(self.constants['output_folder']):
                os.makedirs(self.constants['output_folder'])
            logger_override_string = (
                '{handlers.file_handler.filename: %s}'
                % os.path.join(self.constants['output_folder'], 'log.txt')
            )
            logger_overrides = parse_overrides(logger_override_string)
        logger = setup_logging(log_config, logger_overrides)

        # Automatically log any exceptions that are raised
        sys.excepthook = _logging_excepthook

    def _update_attributes(self, attributes):
        r'''Update the attributes of this class to reflect a set of parameters

        Parameters:
            attributes: A dict that contains the essential parameters for
                running the experiment. Usually loaded from a yaml file using
                `load_extended_yaml()`.

        Author:
            Peter Plantinga 2020
        '''
        for param, new_value in parameters.items():
            if isinstance(new_value, dict):
                value = getattr(self, param, {})
                value.update(new_value)
            else:
                value = new_value
            setattr(self, param, value)


def _logging_excepthook(exc_type, exc_value, exc_traceback):
    """Interrupt exception raising to log the error."""
    logger.error("Exception:", exc_info=(exc_type, exc_value, exc_traceback))
    sys.exit(1)


def parse_arguments(arg_list):
    """Parse command-line arguments to the experiment.

    Parameters:
        arg_list: a list of arguments to parse, most often from sys.argv[1:]

    Example:
        >>> parse_arguments(['--seed', '10'])
        {'seed': 10}

    Author:
        Peter Plantinga 2020
    """
    parser = argparse.ArgumentParser(
        description='Run a SpeechBrain experiment',
    )
    parser.add_argument(
        '--yaml_overrides',
        help='A yaml-formatted string representing a dictionary of '
        'overrides to the parameters in the param file. The keys of '
        'the dictionary can use dots to represent levels in the yaml '
        'hierarchy. For example: "{model.param1: value1}" would '
        'override the param1 parameter of the model node.',
    )
    parser.add_argument(
        '--output_folder',
        help='A folder for storing all experiment-related outputs.',
    )
    parser.add_argument(
        '--seed',
        type=int,
        help='A random seed to reproduce experiments on the same machine',
    )
    parser.add_argument(
        '--log_config',
        help='A file storing the configuration options for logging',
    )

    # Ignore items that are "None", they were not passed
    parsed_args = vars(parser.parse_args(arg_list))
    return {k: v for k, v in parsed_args.items() if v is not None}


def parse_overrides(override_string):
    """Parse overrides from a yaml string representing paired args and values

    Parameters:
        override_string: A yaml-formatted string, where each (key: value) pair
            overrides the same pair in a loaded file.

    Example:
        >>> parse_overrides("{model.arg1: val1, model.arg2.arg3: 3.}")
        {'model': {'arg1': 'val1', 'arg2': {'arg3': 3.0}}}

    Author:
        Peter Plantinga 2020
    """
    preview = {}
    if override_string:
        preview = yaml.safe_load(override_string)

    overrides = {}
    for arg, val in preview.items():
        if '.' in arg:
            nest(overrides, arg.split('.'), val)
        else:
            overrides[arg] = val

    return overrides


def nest(dictionary, args, val):
    """Create a nested sequence of dictionaries, based on an arg list.

    Parameters:
        dictionary (dict): this ref will be updated with the nested arguments.
        args (list): a list of parameters specifying a nested location.
        val (obj): The value to store at the specified nested location.

    Example:
        >>> params = {}
        >>> nest(params, ['arg1', 'arg2', 'arg3'], 'value')
        >>> params
        {'arg1': {'arg2': {'arg3': 'value'}}}

    Author:
        Peter Plantinga 2020
    """
    if len(args) == 1:
        dictionary[args[0]] = val
        return

    if args[0] not in dictionary:
        dictionary[args[0]] = {}

    nest(dictionary[args[0]], args[1:], val)
