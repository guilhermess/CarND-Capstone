#!/usr/bin/env python
import rospy
from std_msgs.msg import Int32
from geometry_msgs.msg import PoseStamped, Pose
from styx_msgs.msg import TrafficLightArray, TrafficLight
from styx_msgs.msg import Lane
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from light_classification.tl_classifier import TLClassifier
import os
import tf
import cv2
import yaml

STATE_COUNT_THRESHOLD = 3
MIN_N_WP_DETECTION_THRESH = 250


class TLDetector(object):
    def __init__(self):
        rospy.init_node('tl_detector', log_level=rospy.DEBUG)

        self.pose = None
        self.waypoints = None
        self.camera_image = None
        self.lights = []

        rospy.Subscriber('/current_pose', PoseStamped, self.pose_cb)
        rospy.Subscriber('/base_waypoints', Lane, self.waypoints_cb)

        '''
        /vehicle/traffic_lights provides you with the location of the traffic
        light in 3D map space and helps you acquire an accurate ground truth
        data source for the traffic light classifier by sending the current
        color state of all traffic lights in the simulator. When testing on
        the vehicle, the color state will not be available. You'll need to
        rely on the position of the light and the camera image to predict it.
        '''
        rospy.Subscriber('/vehicle/traffic_lights', TrafficLightArray,
                         self.traffic_cb)
        rospy.Subscriber('/image_color', Image, self.image_cb)

        config_string = rospy.get_param("/traffic_light_config")
        self.config = yaml.load(config_string)

        self.upcoming_red_light_pub = rospy.Publisher('/traffic_waypoint',
                                                      Int32, queue_size=1)

        self.bridge = CvBridge()
        self.light_classifier = TLClassifier()
        self.listener = tf.TransformListener()

        self.state = TrafficLight.UNKNOWN
        self.last_state = TrafficLight.UNKNOWN
        self.last_wp = -1
        self.state_count = 0
        self.count = 0

        rospy.spin()

    def pose_cb(self, msg):
        self.pose = msg

    def waypoints_cb(self, waypoints):
        self.waypoints = waypoints

    def traffic_cb(self, msg):
        self.lights = msg.lights

    def image_cb(self, msg):
        """Identifies red lights in the incoming camera image and publishes
            the index of the waypoint closest to the red light's stop line to
            /traffic_waypoint

        Args:
            msg (Image): image from car-mounted camera

        """
        self.has_image = True
        self.camera_image = msg
        if self.waypoints:
            light_wp, state = self.process_traffic_lights()

            '''
            Publish upcoming red lights at camera frequency.
            Each predicted state has to occur `STATE_COUNT_THRESHOLD` number
            of times till we start using it. Otherwise the previous stable
            state is used.
            '''
            if self.state != state:
                self.state_count = 0
                self.state = state
            elif self.state_count >= STATE_COUNT_THRESHOLD:
                self.last_state = self.state
                light_wp = light_wp if state == TrafficLight.RED else -1
                self.last_wp = light_wp
                self.upcoming_red_light_pub.publish(Int32(light_wp))
            else:
                self.upcoming_red_light_pub.publish(Int32(self.last_wp))
            self.state_count += 1

    def get_closest_waypoint(self, pose, dist_threshold=None):
        """Identifies the closest path waypoint to the given position
            https://en.wikipedia.org/wiki/Closest_pair_of_points_problem
        Args:
            pose (Pose): position to match a waypoint to

        Returns:
            int: index of the closest waypoint in self.waypoints

        """
        def dl(a, b):
            return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)

        min_distance = None
        index = 0
        i = 0
        for wp in self.waypoints.waypoints:
            pos = wp.pose.pose.position
            distance = dl(pos, pose.position)
            if (min_distance is None or distance < min_distance):
                min_distance = distance
                index = i
            i += 1
        if dist_threshold is None or min_distance < dist_threshold:
            return index
        return -1

    def get_light_state(self, light):
        """Determines the current color of the traffic light

        Args:
            light (TrafficLight): light to classify

        Returns:
            int: ID of traffic light color
            (specified in styx_msgs/TrafficLight)

        """
        if(not self.has_image):
            self.prev_light_loc = None
            return False

        cv_image = self.bridge.imgmsg_to_cv2(self.camera_image, "bgr8")

        # Get classification
        return self.light_classifier.get_classification(cv_image)

    def process_traffic_lights(self):
        """Finds closest visible traffic light, if one exists, and determines its
            location and color

        Returns:
            int: index of waypoint closes to the upcoming stop line for a
                  traffic light (-1 if none exists)
            int: ID of traffic light color
                    (specified in styx_msgs/TrafficLight)

        """
        light = None
        min_light = None
        #stop_line_positions = self.config['stop_line_positions']
        if(self.pose):
            car_waypoint = self.get_closest_waypoint(self.pose.pose)

        min_light_waypoint = -1

        for traffic_light in self.lights:
            light_pos = traffic_light.pose.pose
            light_waypoint = self.get_closest_waypoint(light_pos)

            is_ahead = light_waypoint > car_waypoint
            is_closest = light_waypoint < min_light_waypoint
            light_found = light_waypoint != -1
            min_not_set = min_light_waypoint == -1

            if (light_found and is_ahead and (min_not_set or is_closest)):
                min_light_waypoint = light_waypoint
                min_light = traffic_light

        within_range = ((min_light_waypoint - car_waypoint)
                        < MIN_N_WP_DETECTION_THRESH)

        if min_light_waypoint != -1 and within_range:
            light = self.waypoints.waypoints[min_light_waypoint]

        rospy.logdebug("Car waypoint: %d, light waypoint: %d",
                       car_waypoint, min_light_waypoint)

        if light:
            state = self.get_light_state(min_light)
            return min_light_waypoint, state

        self.count += 1
        return -1, TrafficLight.UNKNOWN


if __name__ == '__main__':
    try:
        TLDetector()
    except rospy.ROSInterruptException:
        rospy.logerr('Could not start traffic node.')
