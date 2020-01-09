import logging
import pickle

from confluent_kafka import Consumer, Producer

from bluesky.run_engine import Dispatcher, DocumentNames


def delivery_report(err, msg):
    """
    Called once for each message produced to indicate delivery result.
    Triggered by poll() or flush().

    Parameters
    ----------
    err
    msg

    Returns
    -------

    """
    if err is not None:
        print("Message delivery failed: {}".format(err))
    else:
        print("Message delivered to topic ""{}"" [partition {}]".format(msg.topic(), msg.partition()))


class Publisher:
    """
    A callback that publishes documents to a Kafka server.

    Reference: https://github.com/confluentinc/confluent-kafka-python/issues/137

    The default configuration of the underlying Kafka Producer is an "idempotent"
    producer. This means three things:
        1) delivery acknowledgement is not sent until all replicate brokers have received a message
        2) message delivery will be retried indefinitely (messages will not be dropped by the Producer)
        3) message order will be maintained

    Parameters
    ----------
    bootstrap_servers : str
        Comma-delimited list of Kafka server addresses as a string such as ``'127.0.0.1:9092'``
    producer_config: dict, optional
        Dictionary configuration information used to construct the underlying Kafka Producer
    serializer: function, optional
        Function to serialize data. Default is pickle.dumps.

    Example
    -------

    Publish from a RunEngine to a Kafka server on localhost on port 9092.

    >>> publisher = Publisher('localhost:9092')
    >>> RE = RunEngine({})
    >>> RE.subscribe(publisher)
    """

    def __init__(
        self, topic, bootstrap_servers, producer_config=None, serializer=pickle.dumps,
    ):
        self.topic = topic
        self.producer_config = {
            "bootstrap.servers": bootstrap_servers,
            "enable.idempotence": True,
            # "enable.idempotence": True is shorthand for the following configuration:
            # "acks": "all",                              # acknowledge only after all brokers receive a message
            # "retries": sys.maxsize,                     # retry indefinitely
            # "max.in.flight.requests.per.connection": 5  # maintain message order when retrying
        }
        if producer_config is not None:
            self.producer_config.update(producer_config)

        self.producer = Producer(self.producer_config)
        self._serializer = serializer

    def __call__(self, name, doc, key=None):
        """

        Parameters
        ----------
        name
        doc
        key

        Returns
        -------

        """
        print(f"KafkaProducer(topic={self.topic} key={key} msg=[name={name} doc={doc}])")
        self.producer.produce(
            topic=self.topic,
            key=key,
            value=self._serializer((name, doc)),
            callback=delivery_report,
        )

    def flush(self):
        self.producer.flush()


class RemoteDispatcher(Dispatcher):
    """
    Dispatch documents received over the network from a Kafka server.

    Parameters
    ----------
    bootstrap_servers : str or tuple
        Address of a Kafka server as a string like ``'127.0.0.1:9092'``
    deserializer: function, optional
        optional function to deserialize data. Default is pickle.loads.

    Example
    -------

    Print all documents generated by remote RunEngines.

    >>> d = RemoteDispatcher('localhost:9092')
    >>> d.subscribe(print)
    >>> d.start()  # runs until interrupted
    """

    def __init__(
        self,
        topics,
        bootstrap_servers,
        *,
        group_id=None,
        auto_offset_reset="latest",
        consumer_config=None,
        deserializer=pickle.loads,
    ):
        logger = logging.getLogger(name=self.__class__.__name__)

        self._deserializer = deserializer

        if consumer_config is None:
            consumer_config = {}
        consumer_config.update(
            {
                "bootstrap.servers": bootstrap_servers,
                "auto.offset.reset": auto_offset_reset,
            }
        )
        if group_id is not None:
            consumer_config["group.id"] = group_id

        logger.info(
            "starting RemoteDispatcher with Kafka Consumer configuration:\n%s",
            consumer_config,
        )
        logger.info("subscribing to Kafka topic(s): %s", topics)

        self.consumer = Consumer(consumer_config)
        self.consumer.subscribe(topics=topics)
        self.closed = False

        super().__init__()

    def _poll(self):
        logger = logging.getLogger(name=self.__class__.__name__)
        while True:
            msg = self.consumer.poll(1.0)

            if msg is None:
                # no message was found
                pass
            elif msg.error():
                logger.error("Kafka Consumer error: %s", msg.error())
            else:
                name, doc = self._deserializer(msg.value())
                logger.debug(
                    "RemoteDispatcher deserialized document with topic %s for Kafka Consumer name: %s doc: %s",
                    msg.topic(),
                    name,
                    doc,
                )
                self.process(DocumentNames[name], doc)

    def start(self):
        if self.closed:
            raise RuntimeError(
                "This RemoteDispatcher has already been "
                "started and interrupted. Create a fresh "
                "instance with {}".format(repr(self))
            )
        try:
            self._poll()
        except Exception:
            self.stop()
            raise

    def stop(self):
        self.consumer.close()
        self.closed = True
