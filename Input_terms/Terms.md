1. **Deterministic Replay:** When a bug can be perfectly reproduced using recorded data (a luxury).
2. **Lane Keep Assist (LKA) Logic:** The "Hello World" of autonomy algorithms.
3. **Highway Pilot Stack:** The relatively clean code path for interstate driving.
4. **Object Tracking (linear):** Following a car moving at constant velocity.
5. **Lookup Table Control:** Using pre-calculated values for simple steering maneuvers.
6. **Sanity Check:** Basic code filters that reject impossible sensor data (e.g., a car flying).
7. **Low-Latency Inference:** When the neural net processes images faster than the frame rate.
8. **Structured Environment:** Coding for roads with perfect paint and no intersections.
9. **Ego-Motion Estimation:** Knowing how the car itself is moving (usually solved via IMU/Odometer).
10. **Keep-in-Lane Planner:** The default state when no obstacles are present.

11. **Voxelization Artifacts:** Losing small details when converting 3D Lidar clouds to processing blocks.

12. **The Handover Latency:** The milliseconds lost between the planner making a decision and the actuators firing.

13. **Sensor Fusion Drift:** When the radar and camera coordinate systems slowly diverge over time.

14. **Non-Convex Optimization:** Trying to find the best path when there are multiple "okay" solutions but no clear winner.

15. **Heisenbug:** A software bug that disappears when you try to debug or log it.

16. **Compute Bottleneck:** When the trunk PC overheats because the vision model is too heavy.

17. **Occlusion Handling:** Guessing what is behind the bus that just stopped.

18. **Temporal Consistency:** Ensuring the AI realizes the car it saw in Frame 1 is the same car in Frame 2.

19. **Trajectory Smoothing:** Preventing the steering wheel from jerking during a path correction.

20. **SLAM Jitter:** When the map jumps around because the Simultaneous Localization and Mapping algorithm is confused.

21. **Overfitting the Training Set:** When the AI is great at driving in Sunnyvale but crashes in Detroit.

22. **Dead Reckoning Decay:** Navigating tunnels without GPS where error accumulates rapidly.

23. **Thread Synchronization:** Ensuring the Lidar, Radar, and Camera threads all talk to the Planner at the exact same timestamp.

24. **Garbage Collection Pauses:** When the coding language (like Java/Python) freezes the car to clear memory.

25. **Edge Case Enumeration:** The impossible task of coding "If" statements for every reality.

26. **Point Cloud Sparsity:** Lidar data that is too "thin" to identify a small object at range.

27. **Adversarial Noise:** Visual patterns that look like static to humans but confuse the neural net.

28. **Mode Confusion:** When the code can't decide if it's in "City Mode" or "Highway Mode."

29. **Cold Start Problem:** The system performance immediately after turning the ignition on.

30. **Prediction Horizon:** How many seconds into the future the AI tries (and fails) to guess.

31. **The "Frozen Robot":** When the planner finds every path unsafe and stops the car in the middle of the road.

32. **Model Quantization Loss:** The accuracy lost when compressing a neural net to run on a car's chip.

33. **Phantom Clusters:** Radar returns from a manhole cover looking like a wall.

34. **Behavioral Cloning Bias:** The AI copying bad habits from human training drivers.

35. **Uncertainty Propagation:** Calculating how unsure the car is about its own unsuredness.

36. **Calibration Drift:** Physical vibrations moving a camera 1mm, ruining depth perception.

37. **Data Ingestion Throttle:** Having too much sensor data to process in real-time.

38. **Context Switching:** The computational cost of switching between different driving algorithms.

39. **Legacy Code Debt:** Old safety rules hard-coded 3 years ago that conflict with new AI models.

40. **High-Definition Map Mismatch:** When the code sees a lane that isn't in the database.

41. **Rule-Based vs. Learned Conflict:** When the "Stop at Red" rule fights the "Creep Forward" neural net.

42. **Optical Flow Failure:** When textureless snow makes visual speed estimation impossible.

43. **Serialization Delay:** Time lost packing data to send it between software modules.

44. **Ackermann Steering Constraints:** Coding path planning for a car that cannot turn in place (non-holonomic).

45. **Dynamic Object Segmentation:** separating a moving cyclist from the static background.

46. **False Negative Suppression:** Tuning the system so it doesn't ignore a real pedestrian.

47. **Inter-Process Communication (IPC) Lag:** The lag between the "eyes" (camera process) and the "brain" (planner process).

48. **Watchdog Timer:** The code that reboots the system if it freezes (terrifying in a moving car).

49. **Memory Leak:** Slow degradation of performance over a long drive.

50. **OTA (Over-the-Air) Bricking:** A software update that renders the car's computer useless.

51. **Pass/Fail Criteria:** Clear-cut rules (e.g., "Did the car hit the cone?").

52. **Regression Testing:** Running yesterday's tests to make sure today's code didn't break them.

53. **Closed-Course Loop:** A simple oval track test for durability.

54. **Unit Testing:** Testing a single function of code in isolation.

55. **Golden Run:** A perfect test drive used as a benchmark.

56. **Static Calibration:** Setting up sensors in a garage with checkerboards.

57. **Log Ingestion:** Uploading the drive data to the server.

58. **Scenario Cataloging:** Creating a list of basic tests (left turn, right turn).

59. **Shadow Mode Validation:** Testing code passively in customer cars without it taking control.

60. **Straight-Line Braking:** Testing emergency stops on a straight track.

61. **Ground Truth Labeling:** The tedious process of manually drawing boxes around cars in video logs to check accuracy.

62. **Scenario Explosion:** The infinite variations of a simple "left turn" (weather, traffic, speed).

63. **Sim-to-Real Gap:** When the code works in the video game (simulator) but fails on asphalt.

64. **False Positive Hell:** When the car reports thousands of "dangers" that weren't there, ruining the test metrics.

65. **Intermittent Faults:** A bug that happens only once every 10,000 miles.

66. **Corner Case Injection:** Trying to artificially create dangerous situations (like a child running out) without killing anyone.

67. **Hardware-in-the-Loop (HIL) Latency:** When the testing rig isn't as fast as the real car.

68. **Disengagement Categorization:** Arguing whether the driver took over because the car failed or because they were scared.

69. **Weather Augmentation:** trying to digitally add rain to clear-day sensor data.

70. **The "Long Tail" of Validation:** The last 1% of scenarios that take 99% of the time to test.

71. **Sensor Cleaning Validation:** Testing if the camera lens washer actually works with mud.

72. **Euro NCAP Protocols:** Strict, specific safety tests required for star ratings.

73. **Test Track Fatigue:** Safety drivers losing focus after driving the same loop for 8 hours.

74. **Data Storage Costs:** The millions of dollars required to store Petabytes of Lidar logs.

75. **Scenario Reconstruction:** Trying to recreate a real-world crash inside a simulation.

76. **Open-Loop Replay:** Feeding recorded data into the software (easy) vs. having the software react to it (hard).

77. **KPI Drift:** When the metrics for "success" change halfway through the project.

78. **Adversarial Validation:** Using AI to automatically generate the hardest possible test scenarios.

79. **Sensor Degradation Testing:** Deliberately scratching lenses or disconnecting wires to see if the car notices.

80. **V2X Interoperability:** Testing if the car talks correctly to traffic lights from different manufacturers.

81. **Geofence Escape:** Testing if the car correctly shuts down when leaving its allowed area.

82. **Dynamic Calibration:** checking if sensors align themselves while driving.

83. **False Negative Rate:** The scariest metric—how often did we miss a real object?

84. **Time-to-Collision (TTC) Accuracy:** Verifying the car knows exactly when it will crash.

85. **Oversensitive Safety Layer:** When the validation car slams on brakes for a blowing leaf.

86. **Fleet Heterogeneity:** Testing software on older cars with different sensors.

87. **Data Bias:** Realizing 90% of your test data is from sunny California.

88. **Labeling Noise:** When human annotators disagree on whether a blob is a rock or a bag.

89. **KPI Gaming:** Engineers writing code specifically to pass the test, not to drive well.

90. **Regression Bombs:** A new feature that unexpectedly breaks a totally unrelated old feature.

91. **Scenario Coverage:** The percentage of all possible driving situations actually tested.

92. **Physical Prototyping:** Building foam targets that look like cars to Radar/Lidar.

93. **Durability Testing:** Running the compute hardware over potholes for 100,000 miles.

94. **Thermal Throttling Tests:** Driving in Death Valley to see if the computer melts.

95. **Public Road Validation:** The legal and logistical nightmare of testing on real streets.

96. **Criticality Assessment:** Deciding which bugs must be fixed before the car can drive.

97. **End-to-End Latency Measurement:** Timing the exact millisecond from photon-in to steering-out.

98. **Human Factors Validation:** Measuring if passengers vomit due to the driving style.

99. **Map Validation:** Checking if the digital map matches the physical road signs.

100. **Zero-Day Exploits:** Security testing for unknown hacker vulnerabilities.

101. **Safe State:** The car stopping and turning on hazards.

102. **QM (Quality Management):** Parts of the system that don't need strict safety ratings (like the infotainment).

103. **Driver Monitoring System (DMS):** Checking if the human is looking at the road (established tech).

104. **Redundancy:** Having two brakes is safer than one.

105. **Operational Design Domain (ODD) Limits:** Simply banning the car from driving in snow.

106. **Passive Safety:** Airbags and seatbelts (the last line of defense).

107. **ISO 26262 Compliance:** The standard checklist for electrical safety.

108. **Heartbeat Signal:** A simple pulse check between components to ensure they are alive.

109. **Emergency Stop:** Hard braking.

110. **Warning Cascade:** Visual -> Audio -> Haptic warnings for the driver.

111. **SOTIF (Safety of the Intended Function):** When the system works as designed, but is still dangerous (e.g., confusing a reflection for a car).

112. **ASIL D Decomposition:** Splitting high-safety requirements across multiple components to save cost.

113. **Controllability:** Determining if a human can overpower a glitching steering wheel.

114. **Foreseeable Misuse:** Predicting that humans will try to sleep in the back seat.

115. **The "Trolley Problem" Ethics:** Programming value judgments into crash scenarios.

116. **Minimum Risk Maneuver (MRM):** Calculating the safest place to pull over on a highway without a shoulder.

117. **Fail-Operational:** The requirement that the car must keep driving safely even after a major computer failure.

118. **Takeover Request (TOR) Timing:** Giving the driver enough time (10s+) to wake up and drive.

119. **Hazard Analysis and Risk Assessment (HARA):** The massive spreadsheet of everything that can go wrong.

120. **Unknown Unsafe Scenarios:** Hazards we don't even know exist yet.

121. **Freedom from Unreasonable Risk:** The vague legal definition of "Safe."

122. **Sensor Blind Spots:** The physical areas around the car the sensors literally cannot see.

123. **Fault Injection Testing:** Deliberately short-circuiting wires to see if the safety logic holds.

124. **Safety Case Argumentation:** The legal document proving to regulators the car is safe.

125. **Mode Confusion Risks:** The danger of the driver thinking the car is driving when it isn't.

126. **Interaction Safety:** Ensuring the AV doesn't scare other human drivers into crashing.

127. **Cybersecurity Gateway:** Preventing a hacker from sending a "Turn Left" command.

128. **Lidar Eye Safety:** Ensuring the lasers don't blind pedestrians.

129. **Actuator Saturation:** When the safety system demands more steering torque than the motor can give.

130. **Dependent Failures:** When the main computer and the backup computer fail for the same reason (e.g., lightning).

131. **Degraded Mode:** How the car behaves when one sensor is broken (limp-home mode).

132. **Fall-back Ready User:** The legal term for the human who is supposed to be paying attention.

133. **Diagnostic Coverage:** The percentage of hardware faults the system can self-detect.

134. **Latent Faults:** A hidden broken backup wire that you don't find until the main wire breaks.

135. **Perception Uncertainty Quantification:** Requiring the AI to say "I am 40% sure that is a human."

136. **Vulnerable Road User (VRU) Priority:** The ethical rule to prioritize pedestrians over property.

137. **Safety Validation Targets:** The statistical proof needed (e.g., 1 billion miles without a fatality).

138. **HMI (Human Machine Interface) overload:** Warning the driver so much they ignore the warnings.

139. **Platooning Risks:** The danger of multiple automated trucks following each other closely.

140. **Wetware Failure:** A cynical term for human error during a handover.

141. **External Human Machine Interface (eHMI):** Communicating intent to pedestrians (e.g., a screen on the grille saying "Walk").

142. **Localization Integrity:** Ensuring the car knows when its GPS is lying.

143. **Watchdog Reset Loops:** When the safety system keeps rebooting the car in a loop.

144. **Over-reliance/Complacency:** The driver trusting the system too much.

145. **Mixed Traffic Hazards:** The chaotic blend of AVs and aggressive human drivers.

146. **Post-Crash Response:** Ensuring the high-voltage battery cuts off after an accident.

147. **Safety Culture:** Trying to stop engineers from shipping code just to meet a deadline.

148. **Validation Coverage Gaps:** The fear that the test track didn't match the real world.

149. **Regulatory Divergence:** Safety rules that are different in Germany vs. USA vs. China.

150. **The Black Box (EDR):** Ensuring data is saved securely after a catastrophic failure.

151. **The Demo Route:** A carefully curated path where the car never fails.

152. **Parking Assist:** A flashy feature that is easy to sell and relatively easy to build.

153. **Highway Chauffeur:** The most marketable "hands-off" feature.

154. **Green Light Notification:** A simple "ding" when the light turns green (high value, low effort).

155. **Start of Production (SOP):** The finish line (optimistically).

156. **Visualizer/UI:** Making the screen look cool so passengers trust the robot.

157. **OTA Update:** Sending a feature after the car is sold.

158. **Milestone Payment:** Getting paid by the OEM when a feature works.

159. **Proof of Concept (PoC):** A rough prototype that proves it *can* work.

160. **The "Wow" Factor:** Any feature that impresses investors.

161. **The Trough of Disillusionment:** When the hype dies and the engineering gets hard.

162. **Feature Creep:** Adding "just one more thing" that delays the launch by 6 months.

163. **Bill of Materials (BOM) Cost:** The Lidar is too expensive for a consumer car.

164. **Level 3 Liability:** The business risk of taking responsibility for accidents.

165. **The "99% Done" Illusion:** The last 1% of autonomy takes 50% of the budget.

166. **Geofence Constraints:** Selling a "Self-Driving Car" that only works in South Phoenix.

167. **Vendor Lock-in:** Being stuck with a chip supplier that delays delivery.

168. **MVP (Minimum Viable Product):** The struggle to define what "barely working" looks like for a safety product.

169. **Compute Power vs. Power Consumption:** The chips are fast enough, but they drain the EV battery too fast.

170. **Regulation Delays:** Waiting for the government to legalize steering wheels that retract.

171. **Public Perception:** Managing PR after a competitor's car crashes.

172. **Scalability:** It works on 5 prototypes, but can we build 500,000?

173. **Subscription Fatigue:** Will customers pay $100/month for self-driving?

174. **Mapping Costs:** The recurring cost of keeping HD maps up to date.

175. **Sensor Stack Integration:** Trying to fit 12 cameras into a car design without it looking ugly.

176. **Data Privacy Laws (GDPR):** You can't record pedestrians' faces in Europe.

177. **Teleoperation Costs:** Paying humans to remotely monitor the fleet is expensive.

178. **Use Case Definition:** Realizing customers don't actually want a robo-taxi, they want a cheaper commute.

179. **Legacy Architecture:** Trying to put AI on a car built with 1990s networking (CAN bus).

180. **Supply Chain Shortage:** We have the code, but no chips to run it on.

181. **Disengagement Rate Targets:** The boss wants 10k miles between failures; we are at 100.

182. **Technical Debt:** We built the demo fast/dirty, now we have to rebuild it for production.

183. **Return on Investment (ROI):** We spent billions; where is the profit?

184. **Market Fragmentation:** Building different software for Left-Hand Drive vs. Right-Hand Drive markets.

185. **User Trust Calibration:** Customers trusting the system *too much* and napping, or *too little* and turning it off.

186. **Hardware Freeze:** The moment you can't change the sensors anymore, even if better ones exist.

187. **System Integration:** The nightmare of putting the software, sensors, and chassis together.

188. **Warranty Claims:** Who pays when the AI scrapes a rim?

189. **Feature Parity:** Trying to catch up to Tesla/Waymo.

190. **The "Uncanny Valley" of Driving:** The car drives technically well, but feels "weird" to passengers.

191. **Customer Education:** Teaching users that "Autopilot" doesn't mean they can sleep.

192. **Infrastructure Dependency:** We need smart traffic lights, but the city won't build them.

193. **Unit Economics:** The cost per mile of a robotaxi vs. an Uber driver.

194. **Safety Driver Logistics:** Hiring and managing 500 people to sit in cars all day.

195. **Version Control Chaos:** Fleet A has v1.0, Fleet B has v1.2, and they behave differently.

196. **Third-Party Certification:** Paying a company to stamp "Safe" on the product.

197. **Intellectual Property (IP) Theft:** Engineers leaving to join a competitor.

198. **Pivot:** Changing the company strategy from "Robotaxi" to "Trucking" because it's easier.

199. **Burn Rate:** How much cash the company loses every month.

200. **Vaporware:** Announced features that don't actually exist yet.