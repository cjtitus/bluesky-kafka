import os
import tempfile

from contextlib import contextmanager

import intake
import numpy as np
import pytest
import yaml

from bluesky.tests.conftest import RE  # noqa
from ophyd.tests.conftest import hw  # noqa

from bluesky_kafka import BlueskyConsumer, Publisher
from bluesky_kafka.consume import BasicConsumer
from bluesky_kafka.produce import BasicProducer
from bluesky_kafka.utils import create_topics, delete_topics


TEST_TOPIC = "bluesky-kafka-test"
TEST_TOPIC2 = "bluesky2-kafka-test"


def pytest_addoption(parser):
    """
    Add `--kafka-bootstrap-servers` to the pytest command line parser.
    """
    parser.addoption(
        "--kafka-bootstrap-servers",
        action="store",
        default="127.0.0.1:9092",
        help="comma-separated list of address:port for Kafka bootstrap servers",
    )


@pytest.fixture(scope="function")
def kafka_bootstrap_servers(request):
    """
    Return a comma-delimited string of Kafka bootstrap server host:port specified
    on the pytest command line with option --kafka-bootstrap-servers.

    Parameters
    ----------
    request : pytest request fixture

    Returns
    -------
    comma-delimited string of Kafka bootstrap server host:port
    """
    return request.config.getoption("--kafka-bootstrap-servers")


@pytest.fixture(scope="function")
def broker_authorization_config():
    return {
        # "security.protocol": "SASL_PLAINTEXT",
        # "sasl.mechanisms": "PLAIN",
        # "sasl.username": "user",
        # "sasl.password": "password",
    }


@pytest.fixture(scope="function")
def temporary_topics(kafka_bootstrap_servers, broker_authorization_config):
    """
    Use this "factory as a fixture and context manager" to cleanly
    create new topics and delete them after a test.

    If `bootstrap_servers` is not specified to the factory function
    then the `kafka_bootstrap_servers` fixture will be used.

    Parameters
    ----------
    kafka_bootstrap_servers : pytest fixture
        comma-delimited str of Kafka bootstrap server host:port specified on the pytest command line
    broker_authorization_config: dict
        Kafka broker authentication parameters for the test broker
    """

    @contextmanager
    def _temporary_topics(topics, bootstrap_servers=None, admin_client_config=None):
        if bootstrap_servers is None:
            bootstrap_servers = kafka_bootstrap_servers

        if admin_client_config is None:
            admin_client_config = broker_authorization_config

        try:
            # delete existing requested topics
            # this will delete any un-consumed messages
            # the intention is to make tests repeatable by ensuring
            # they always start with a topics having no "old" messages
            delete_topics(
                bootstrap_servers=bootstrap_servers,
                topics_to_delete=topics,
                admin_client_config=admin_client_config,
            )
            create_topics(
                bootstrap_servers=bootstrap_servers,
                topics_to_create=topics,
                admin_client_config=admin_client_config,
            )
            yield topics
        finally:
            delete_topics(
                bootstrap_servers=bootstrap_servers,
                topics_to_delete=topics,
                admin_client_config=admin_client_config,
            )

    return _temporary_topics


@pytest.fixture(scope="function")
def basic_producer_factory(kafka_bootstrap_servers, broker_authorization_config):
    """
    Use this "factory as a fixture" to create one or more BasicProducers in a test function.
    If `bootstrap_servers` is not specified to the factory function then the `kafka_bootstrap_servers`
    fixture will be used. The `serializer` parameter can be passed through **kwargs of the factory function.

    For example:

        def test_something(basic_producer_factory):
            basic_producer_abc = basic_producer_factory(topic="abc")
            basic_producer_xyz = basic_producer_factory(topic="xyz", serializer=pickle.dumps)
            ...

    Parameters
    ----------
    kafka_bootstrap_servers : pytest fixture
        comma-delimited str of Kafka bootstrap server host:port specified on the pytest command line
    broker_authorization_config: dict
        Kafka broker authentication parameters for the test broker

    Returns
    -------
    _basic_producer_factory : function(topic, key, producer_config, **kwargs)
        a factory function returning bluesky_kafka.produce.BasicProducer instances constructed with the
        specified arguments
    """

    def _basic_producer_factory(
        topic,
        bootstrap_servers=None,
        key=None,
        producer_config=None,
        **kwargs,
    ):
        """
        Parameters
        ----------
        topic : str
            Topic to which all messages will be published.
        bootstrap_servers: sequence of str
            List of Kafka broker addresses as strings such as ``["127.0.0.1:9092"]``;
            default is the value of the pytest command line parameter --kafka-bootstrap-servers
        key : str
            Kafka "key" string. Specify a key to maintain message order. If None is specified
            no ordering will be imposed on messages.
        producer_config : dict, optional
            Dictionary configuration information used to construct the underlying Kafka Producer.
        **kwargs
            **kwargs will be passed to bluesky_kafka.produce.BasicProducer() and may include on_delivery,
            and serializer

        Returns
        -------
        basic_producer : bluesky_kafka.produce.BasicProducer
            a BasicProducer instance constructed with the specified arguments
        """
        if bootstrap_servers is None:
            bootstrap_servers = kafka_bootstrap_servers.split(",")

        if producer_config is None:
            # this default configuration is not guaranteed
            # to be generally appropriate
            producer_config = {
                "acks": 1,
                "enable.idempotence": False,
                "request.timeout.ms": 1000,
            }
            producer_config.update(broker_authorization_config)

        return BasicProducer(
            topic=topic,
            key=key,
            bootstrap_servers=bootstrap_servers,
            producer_config=producer_config,
            **kwargs,
        )

    return _basic_producer_factory


@pytest.fixture(scope="function")
def consume_kafka_messages(kafka_bootstrap_servers, broker_authorization_config):
    """Use this fixture to consume the specified count of Kafka messages.

    This fixture will construct a BasicConsumer and run its polling loop. When the specified
    message count is reached the polling loop will terminate.

    Parameters
    ----------
    kafka_bootstrap_servers : pytest fixture
        comma-delimited str of Kafka bootstrap server host:port specified on the pytest command line
    broker_authorization_config: dict
        Kafka broker authentication parameters for the test broker

    Returns
    -------
    _consume_kafka_messages: function(topic, bootstrap_servers=None, **basic_consumer_kwargs) -> List[object]
        calling this function will consume Kafka messages and place the message "payloads"
        into a list; when the expected number of messages have been consumed the consumer
        polling loop will terminate and the payload list will be returned
    """

    def _consume_kafka_messages(
        expected_message_count,
        kafka_topic,
        bootstrap_servers=None,
        consumer_config=None,
        **basic_consumer_kwargs,
    ):
        """
        Parameters
        ----------
        expected_message_count: int
            the number of messages to consume, must be greater than 0
        kafka_topic: str
            Kafka messages with this topic will be consumed
        bootstrap_servers: str, optional
            List of Kafka server addresses as strings such as ``["127.0.0.1:9092"]``;
            default is the value of the pytest command line parameter --kafka-bootstrap-servers
        consumer_config: dict, optional
            Dictionary of Kafka consumer configuration parameters
        basic_consumer_kwargs:
            Allows polling_duration and deserializer to be passed the the BasicConsumer's __init__

        Returns
        -------
         consumed_bluesky_documents: list
             list of (name, document) tuples delivered by Kafka
        """
        if expected_message_count > 0:
            pass
        else:
            raise ValueError(
                f"'expected_message_count' was {expected_message_count}, but must be greater than 0"
            )

        if bootstrap_servers is None:
            bootstrap_servers = kafka_bootstrap_servers.split(",")

        if consumer_config is None:
            consumer_config = {
                # this consumer is intended to read messages that
                # have already been published, so it is necessary
                # to specify "earliest" here
                "auto.offset.reset": "earliest",
            }
            consumer_config.update(broker_authorization_config)

        consumed_messages = []

        def store_consumed_message(consumer, topic, message):
            """This function appends to a list all messages received by the consumer.

            Parameters
            ----------
            consumer: bluesky_kafka.consume.BasicConsumer
                unused
            topic: str
                unused
            message: object
                deserialized "value" of the Kafka message
            """
            consumed_messages.append(message)

        basic_consumer = BasicConsumer(
            topics=[kafka_topic],
            bootstrap_servers=bootstrap_servers,
            group_id=f"{kafka_topic}.basic.consumer.group",
            consumer_config=consumer_config,
            process_message=store_consumed_message,
            **basic_consumer_kwargs,
        )

        def until_message_count_reached():
            """
            This function returns False to end the BasicConsumer polling loop after seeing
            the expected number of messages. Without something like this the polling loop
            will never end.
            """
            return len(consumed_messages) < expected_message_count

        try:
            # start() will return when 'until_message_count_reached' returns False
            basic_consumer.start_polling(
                continue_polling=until_message_count_reached,
            )
        finally:
            return consumed_messages, basic_consumer

    return _consume_kafka_messages


@pytest.fixture(scope="function")
def publisher_factory(kafka_bootstrap_servers, broker_authorization_config):
    """
    Use this "factory as a fixture" to create one or more Publishers in a test function.
    If `bootstrap_servers` is not specified to the factory function then the `kafka_bootstrap_servers`
    fixture will be used. The `serializer` parameter can be passed through **kwargs of the factory function.

    For example:

        def test_something(publisher_factory):
            publisher_abc = publisher_factory(topic="abc")
            publisher_xyz = publisher_factory(topic="xyz", serializer=pickle.dumps)
            ...

    Parameters
    ----------
    kafka_bootstrap_servers : pytest fixture
        comma-delimited str of Kafka bootstrap server host:port specified on the pytest command line
    broker_authorization_config: dict
        Kafka broker authentication parameters for the test broker

    Returns
    -------
    _publisher_factory : function(topic, key, producer_config, flush_on_stop_doc, **kwargs)
        a factory function returning bluesky_kafka.Publisher instances constructed with the
        specified arguments
    """

    def _publisher_factory(
        topic,
        bootstrap_servers=None,
        key=None,
        producer_config=None,
        **kwargs,
    ):
        """
        Parameters
        ----------
        topic : str
            Topic to which all messages will be published.
        bootstrap_servers: str
            Comma-delimited list of Kafka server addresses as a string such as ``'127.0.0.1:9092'``;
            default is the value of the pytest command line parameter --kafka-bootstrap-servers
        key : str
            Kafka "key" string. Specify a key to maintain message order. If None is specified
            no ordering will be imposed on messages.
        producer_config : dict, optional
            Dictionary configuration information used to construct the underlying Kafka Producer.
        **kwargs
            **kwargs will be passed to bluesky_kafka.Publisher() and may include on_delivery,
            flush_on_stop_doc, and serializer

        Returns
        -------
        publisher : bluesky_kafka.Publisher
            a Publisher instance constructed with the specified arguments
        """
        if bootstrap_servers is None:
            bootstrap_servers = kafka_bootstrap_servers

        if producer_config is None:
            # this default configuration is not guaranteed
            # to be generally appropriate
            producer_config = {
                "acks": 1,
                "enable.idempotence": False,
                "request.timeout.ms": 1000,
            }
            producer_config.update(broker_authorization_config)

        return Publisher(
            topic=topic,
            key=key,
            bootstrap_servers=bootstrap_servers,
            producer_config=producer_config,
            **kwargs,
        )

    return _publisher_factory


@pytest.fixture(scope="function")
def consume_documents_from_kafka_until_first_stop_document(
    kafka_bootstrap_servers, broker_authorization_config
):
    """Use this fixture to consume Kafka messages containing bluesky (name, document) tuples.

    This fixture will construct a BlueskyConsumer and run its polling loop. When the first
    stop document is encountered the consumer polling loop will terminate so the test function
    can continue.

    Parameters
    ----------
    kafka_bootstrap_servers : pytest fixture
        comma-delimited str of Kafka bootstrap server host:port specified on the pytest command line
    broker_authorization_config: dict
        Kafka broker authentication parameters for the test broker

    Returns
    -------
    _consume_documents_from_kafka:
            function(topic, bootstrap_servers=None, **bluesky_consumer_kwargs) -> List[(name, document)]
        calling this function will consume Kafka messages and place the (name, document)
        tuples into a list; when the first stop document is encountered the consumer
        polling loop will terminate and the document list will be returned
    """

    def _consume_documents_from_kafka(
        kafka_topic,
        bootstrap_servers=None,
        consumer_config=None,
        **bluesky_consumer_kwargs,
    ):
        """
        Parameters
        ----------
        kafka_topic: str
            Kafka messages with this topic will be consumed
        bootstrap_servers: str, optional
            Comma-delimited list of Kafka server addresses as a string such as ``'127.0.0.1:9092'``;
            default is the value of the pytest command line parameter --kafka-bootstrap-servers
        consumer_config: dict, optional
            Dictionary of Kafka consumer configuration parameters
        bluesky_consumer_kwargs:
            Allows polling_duration and deserializer to be passed the the BlueskyConsumer

        Returns
        -------
         consumed_bluesky_documents: list
             list of (name, document) tuples delivered by Kafka
        """
        if bootstrap_servers is None:
            bootstrap_servers = kafka_bootstrap_servers

        if consumer_config is None:
            consumer_config = {
                # this consumer is intended to read messages that
                # have already been published, so it is necessary
                # to specify "earliest" here
                "auto.offset.reset": "earliest",
            }
            consumer_config.update(broker_authorization_config)

        consumed_bluesky_documents = []

        def store_consumed_document(consumer, topic, name, document):
            """This function appends to a list all documents received by the consumer.

            Parameters
            ----------
            consumer: bluesky_kafka.BlueskyConsumer
                unused
            topic: str
                unused
            name: str
                bluesky document name, such as "start", "descriptor", "event", etc
            document: dict
                dictionary of bluesky document data
            """
            consumed_bluesky_documents.append((name, document))

        bluesky_consumer = BlueskyConsumer(
            topics=[kafka_topic],
            bootstrap_servers=bootstrap_servers,
            group_id=f"{kafka_topic}.consumer.group",
            consumer_config=consumer_config,
            process_document=store_consumed_document,
            **bluesky_consumer_kwargs,
        )

        def until_first_stop_document():
            """
            This function returns False to end the BlueskyConsumer polling loop after seeing
            a "stop" document. Without something like this the polling loop will never end.
            """
            if "stop" in [name for name, _ in consumed_bluesky_documents]:
                return False
            else:
                return True

        # start() will return when 'until_first_stop_document' returns False
        bluesky_consumer.start(
            continue_polling=until_first_stop_document,
        )

        return consumed_bluesky_documents

    return _consume_documents_from_kafka


@pytest.fixture(scope="function")
def publisher(request, kafka_bootstrap_servers, broker_authorization_config):
    # work with a single broker
    producer_config = {
        "acks": 1,
        "enable.idempotence": False,
        "request.timeout.ms": 5000,
    }
    producer_config.update(broker_authorization_config)

    return Publisher(
        topic=TEST_TOPIC,
        bootstrap_servers=kafka_bootstrap_servers,
        key="kafka-unit-test-key",
        producer_config=producer_config,
        flush_on_stop_doc=True,
    )


@pytest.fixture(scope="function")
def publisher2(request, kafka_bootstrap_servers, broker_authorization_config):
    # work with a single broker
    producer_config = {
        "acks": 1,
        "enable.idempotence": False,
        "request.timeout.ms": 5000,
    }
    producer_config.update(broker_authorization_config)

    return Publisher(
        topic=TEST_TOPIC2,
        bootstrap_servers=kafka_bootstrap_servers,
        key="kafka-unit-test-key",
        # work with a single broker
        producer_config=producer_config,
        flush_on_stop_doc=True,
    )


@pytest.fixture(scope="function")
def mongo_client(request):
    mongobox = pytest.importorskip("mongobox")
    box = mongobox.MongoBox()
    box.start()
    return box.client()


@pytest.fixture(scope="function")
def mongo_uri(request, mongo_client):
    return f"mongodb://{mongo_client.address[0]}:{mongo_client.address[1]}"


@pytest.fixture(scope="function")
def numpy_md(request):
    return {
        "numpy_data": {"nested": np.array([1, 2, 3])},
        "numpy_scalar": np.float64(3),
        "numpy_array": np.ones((3, 3)),
    }


@pytest.fixture(scope="function")
def data_broker(request, mongo_uri):
    TMP_DIR = tempfile.mkdtemp()
    YAML_FILENAME = "intake_test_catalog.yml"

    fullname = os.path.join(TMP_DIR, YAML_FILENAME)

    # Write a catalog file.
    with open(fullname, "w") as f:
        f.write(
            f"""
sources:
  xyz:
    description: Some imaginary beamline
    driver: "bluesky-mongo-normalized-catalog"
    container: catalog
    args:
      metadatastore_db: {mongo_uri}/{TEST_TOPIC}
      asset_registry_db: {mongo_uri}/{TEST_TOPIC}
      handler_registry:
        NPY_SEQ: ophyd.sim.NumpySeqHandler
    metadata:
      beamline: "00-ID"
  xyz2:
    description: Some imaginary beamline
    driver: "bluesky-mongo-normalized-catalog"
    container: catalog
    args:
      metadatastore_db: {mongo_uri}/{TEST_TOPIC2}
      asset_registry_db: {mongo_uri}/{TEST_TOPIC2}
      handler_registry:
        NPY_SEQ: ophyd.sim.NumpySeqHandler
    metadata:
      beamline: "00-ID"
                """
        )

    def load_config(filename):
        package_directory = os.path.dirname(os.path.abspath(__file__))
        filename = os.path.join(package_directory, filename)
        with open(filename) as f:
            return yaml.load(f, Loader=getattr(yaml, "FullLoader", yaml.Loader))

    # Create a databroker with the catalog config file.
    return intake.open_catalog(fullname)
